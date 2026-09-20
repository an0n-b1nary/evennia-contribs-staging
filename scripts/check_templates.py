"""Compile every Django template in the repo and fail on the syntax-error class.

Run as a pre-commit hook (receives candidate paths as positional arguments) or
with no arguments to sweep the whole tree.

A broken template is invisible to the test suite unless a test actually
*renders* the page it belongs to: building a view's context compiles nothing,
so a page can be a guaranteed 500 while its view tests stay green. This sweep
compiles every template unconditionally, so the whole class is caught at commit
time rather than by a visitor.

The sweep covers syntax, comment, recursion, and web-markup conventions:

1.  **It compiles at all.** Catches unbalanced tags, unknown filters, leading-
    underscore variable lookups (``{{ board._post_count }}``), and tags nested
    inside a quoted argument (``with cancel_url="{% url 'x' %}"``) -- the latter
    reads naturally but the tokenizer ends the outer tag at the first ``%}``.

2.  **No multi-line ``{# ... #}``.** Django's tokenizer regex has no DOTALL, so
    a comment spanning lines is not a comment: its contents are parsed as live
    template source. A usage example inside one becomes a real ``{% include %}``.

3.  **No template includes itself.** The usual way check 2 turns fatal -- a
    partial documenting its own usage recursed until RecursionError.

4.  **Web conventions.** The nine web contribs must use namespaced or allowed
    Bootstrap 4 classes, external stylesheets, scroll wrappers around tables,
    and empty states for content loops. See ``UI_CONVENTIONS.md``.

Compilation needs Django, but nothing else: no settings module, no database, no
game directory. If Django is not importable the sweep prints a hint and exits 0,
matching the anonymity guard's "don't block a bare clone" behaviour; pass
``--require-django`` (as CI does) to make that a hard failure instead.
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".venv_sandbox", "ci_game"}

# Libraries a contrib template may {% load %}. Only the importable ones are
# installed, so a missing optional dependency degrades to "that {% load %}
# fails" rather than crashing the sweep.
CANDIDATE_APPS = [
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "sekizai",
]

# Django's own tag_re, minus the {% %} alternative: we only want comment opens.
COMMENT_OPEN = re.compile(r"\{#")

WEB_CONTRIBS = {
    "evennia_boards",
    "evennia_calendar",
    "evennia_jobs",
    "evennia_lore",
    "evennia_maps",
    "evennia_plots",
    "evennia_regions",
    "evennia_scenes",
    "evennia_xp",
}

# Bootstrap 4 utility families used by the contrib templates. Keeping this
# list here makes a new custom class fail loudly instead of becoming another
# host-specific styling convention.
BOOTSTRAP4_EXACT = {
    "active",
    "alert",
    "alert-danger",
    "alert-info",
    "alert-success",
    "alert-warning",
    "align-items-center",
    "align-items-start",
    "align-middle",
    "badge",
    "badge-danger",
    "badge-info",
    "badge-primary",
    "badge-secondary",
    "badge-success",
    "badge-warning",
    "bg-danger",
    "bg-info",
    "bg-primary",
    "bg-secondary",
    "bg-success",
    "bg-transparent",
    "bg-warning",
    "border",
    "border-secondary",
    "border-warning",
    "blockquote",
    "breadcrumb",
    "breadcrumb-item",
    "btn",
    "btn-danger",
    "btn-outline-danger",
    "btn-outline-primary",
    "btn-outline-secondary",
    "btn-outline-warning",
    "btn-primary",
    "btn-secondary",
    "btn-sm",
    "btn-success",
    "btn-warning",
    "card",
    "card-body",
    "card-header",
    "card-text",
    "col-md-4",
    "col-sm-10",
    "col-sm-2",
    "col-sm-4",
    "col-sm-8",
    "container",
    "d-block",
    "d-flex",
    "d-inline",
    "d-inline-flex",
    "disabled",
    "flex-shrink-0",
    "flex-wrap",
    "float-right",
    "font-weight-bold",
    "form-check",
    "form-check-input",
    "form-check-label",
    "form-control",
    "form-control-sm",
    "form-group",
    "form-inline",
    "form-text",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "invalid-feedback",
    "lead",
    "list-group",
    "list-group-item",
    "list-inline",
    "list-inline-item",
    "list-unstyled",
    "justify-content-between",
    "justify-content-center",
    "mb-0",
    "mb-1",
    "mb-2",
    "mb-3",
    "mb-4",
    "mb-5",
    "ml-1",
    "ml-2",
    "ml-3",
    "mr-1",
    "mr-2",
    "mr-3",
    "mt-0",
    "mt-1",
    "mt-2",
    "mt-3",
    "mt-4",
    "mt-5",
    "mx-auto",
    "nav",
    "page-item",
    "page-link",
    "pagination",
    "p-2",
    "pl-0",
    "pr-0",
    "py-0",
    "py-1",
    "py-2",
    "py-5",
    "rounded",
    "row",
    "small",
    "sr-only",
    "table",
    "table-bordered",
    "table-sm",
    "table-striped",
    "table-hover",
    "thead-dark",
    "text-center",
    "text-danger",
    "text-dark",
    "text-info",
    "text-muted",
    "text-right",
    "text-success",
    "text-warning",
    "text-white",
    "text-decoration-none",
    "w-100",
    "w-auto",
}

STRUCTURAL_LOOP_CONTEXTS = {
    "form",
    "diff_lines",
    "layers",
    "svg.tiles",
    "page_obj.paginator.page_range",
    "cal_weeks_with_events",
    "week",
    "emphasis_choices",
    "status_choices",
    "arc_type_choices",
}


def is_web_contrib_template(path: Path) -> bool:
    """Return whether path belongs to one of the nine web contribs."""
    return "contribs" in path.parts and any(name in path.parts for name in WEB_CONTRIBS)


def _bootstrap4_class(token: str) -> bool:
    """Recognize Bootstrap 4 classes without enumerating every utility value."""
    if token in BOOTSTRAP4_EXACT:
        return True
    if re.fullmatch(r"[mp][trblxy]?-(?:(?:sm|md|lg|xl)-)?(?:[0-5]|auto)", token):
        return True
    if re.fullmatch(r"col(?:-(?:sm|md|lg|xl))?(?:-(?:[1-9]|1[0-2]|auto))?", token):
        return True
    return bool(
        re.fullmatch(r"offset-(?:(?:sm|md|lg|xl)-)?(?:[0-9]|1[01])", token)
        or re.fullmatch(r"display-[1-4]", token)
        or re.fullmatch(r"[wh]-(?:25|50|75|100|auto)", token)
        or re.fullmatch(r"text-(?:(?:sm|md|lg|xl)-)?(?:left|right|center)", token)
    )


def _without_template_comments(source: str) -> str:
    """Ignore template documentation while preserving diagnostic line numbers."""
    return re.sub(
        r"\{%\s*comment\b.*?%\}.*?\{%\s*endcomment\s*%\}|\{#[^\n]*?#\}",
        lambda match: "\n" * match.group().count("\n"),
        source,
        flags=re.DOTALL,
    )


class _MarkupConventionParser(HTMLParser):
    """Check literal HTML structure while tolerating Django template syntax."""

    def __init__(self, path: Path, app_name: str):
        super().__init__(convert_charrefs=False)
        self.path = path
        self.app_name = app_name
        self.errors: list[str] = []
        self._stack: list[tuple[str, dict[str, str]]] = []

    def _line(self) -> int:
        return self.getpos()[0]

    def handle_starttag(self, tag, attrs):
        values = {key: value or "" for key, value in attrs}
        if "style" in values:
            self.errors.append(f"{self.path}:{self._line()}: inline style attributes are forbidden")
        if tag == "style":
            self.errors.append(f"{self.path}:{self._line()}: embedded <style> blocks are forbidden")

        if tag == "table":
            wrappers = [attrs.get("class", "") for _, attrs in self._stack]
            required = f"evennia-{self.app_name}-table-scroll"
            if not any(required in classes.split() for classes in wrappers):
                self.errors.append(f"{self.path}:{self._line()}: <table> must be inside {required}")

        classes = values.get("class", "")
        classes = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", classes)
        for token in classes.split():
            if "{" in token or "}" in token:
                continue
            if _bootstrap4_class(token) or token.startswith(f"evennia-{self.app_name}-"):
                continue
            self.errors.append(
                f"{self.path}:{self._line()}: class '{token}' is not Bootstrap 4 or "
                f"namespaced evennia-{self.app_name}-*"
            )
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self._stack.append((tag, values))

    def handle_startendtag(self, tag, attrs):
        depth = len(self._stack)
        self.handle_starttag(tag, attrs)
        del self._stack[depth:]

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break


def check_markup_conventions(path: Path, source: str) -> list[str]:
    """Check CSS ownership and class/table conventions in one web template."""
    if not is_web_contrib_template(path):
        return []
    app_name = next(name.removeprefix("evennia_") for name in WEB_CONTRIBS if name in path.parts)
    parser = _MarkupConventionParser(path, app_name)
    source = _without_template_comments(source)
    # Template expressions can contain quotes inside quoted HTML attributes.
    # Mask them before parsing, retaining literal classes in every branch.
    source = re.sub(
        r"\{%.*?%\}|\{\{.*?\}\}",
        lambda match: " " + "\n" * match.group().count("\n"),
        source,
        flags=re.DOTALL,
    )
    parser.feed(source)
    parser.close()
    return parser.errors


def check_list_loops(path: Path, source: str) -> list[str]:
    """Require empty branches or empty-state includes for content loops."""
    if not is_web_contrib_template(path):
        return []
    try:
        from django.template.base import Lexer, TokenType
    except ImportError:
        return []

    errors = []
    stack: list[dict] = []
    completed: list[dict] = []
    if_stack: list[dict] = []
    for token in Lexer(_without_template_comments(source)).tokenize():
        if token.token_type is not TokenType.BLOCK:
            continue
        command = token.contents.split(None, 1)[0] if token.contents else ""
        if command == "if":
            parts = token.contents.split()
            if_stack.append({"context": parts[1] if len(parts) == 2 else "", "loops": []})
        elif command == "elif" and if_stack:
            if_stack[-1]["context"] = ""
        elif command == "else" and if_stack:
            if_context = if_stack[-1]["context"]
            for record in if_stack[-1]["loops"]:
                if record["context"].removesuffix(".items") == if_context:
                    record["outer_empty"] = True
            # A loop in the else branch cannot use that branch as its empty state.
            if_stack[-1]["context"] = ""
        elif command == "endif" and if_stack:
            if_stack.pop()
        elif command == "for":
            parts = token.split_contents()
            if "in" not in parts or parts.index("in") + 1 == len(parts):
                continue  # Compilation reports malformed for tags.
            context = parts[parts.index("in") + 1]
            record = {
                "context": context,
                "line": token.lineno,
                "has_empty": False,
                "outer_empty": False,
                "structural": context in STRUCTURAL_LOOP_CONTEXTS
                or context.endswith((".errors", ".non_field_errors")),
            }
            stack.append(record)
            for frame in if_stack:
                frame["loops"].append(record)
        elif command == "empty" and stack:
            stack[-1]["has_empty"] = True
        elif command == "endfor" and stack:
            record = stack.pop()
            completed.append(record)
    for record in completed:
        context = record["context"]
        if not record["structural"] and not record["has_empty"] and not record["outer_empty"]:
            errors.append(
                f"{path}:{record['line']}: loop over '{context}' needs an {{% empty %}} "
                "branch or an empty-state include"
            )
    return errors


def iter_templates(paths: list[str]) -> list[Path]:
    """Return the .html files to check, from explicit paths or a full sweep."""
    if paths:
        return [p for raw in paths if (p := Path(raw)).is_file() and p.suffix == ".html"]
    found = []
    for path in REPO_ROOT.rglob("*.html"):
        if SKIP_DIRS.isdisjoint(path.parts):
            found.append(path)
    return sorted(found)


def template_name(path: Path) -> str | None:
    """The name this file is included/extended by, relative to its templates root."""
    parts = path.resolve().parts
    if "templates" not in parts:
        return None
    root = len(parts) - 1 - parts[::-1].index("templates")
    return "/".join(parts[root + 1 :])


def check_multiline_comments(path: Path, source: str) -> list[str]:
    """Flag any {# that is not closed on the same line."""
    errors = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for match in COMMENT_OPEN.finditer(line):
            if "#}" not in line[match.end() :]:
                errors.append(
                    f"{path}:{lineno}: multi-line '{{#' comment. Django's comment "
                    "syntax is single-line only -- everything after this point is "
                    "parsed as live template source. Use {% comment %}...{% endcomment %}."
                )
    return errors


def constant_template_names(compiled) -> list[str]:
    """Literal template names named by {% include %}/{% extends %} tags."""
    from django.template.loader_tags import ExtendsNode, IncludeNode

    names = []
    for node_type in (IncludeNode, ExtendsNode):
        for node in compiled.nodelist.get_nodes_by_type(node_type):
            target = getattr(node, "parent_name", None) or getattr(node, "template", None)
            # FilterExpression.var is a plain str for a quoted constant, and a
            # Variable for anything resolved at render time (which we can't check).
            var = getattr(target, "var", None)
            if isinstance(var, str):
                names.append(var)
    return names


def check_template(path: Path, engine) -> list[str]:
    """Compile one template and return human-readable errors, if any."""
    from django.template import TemplateSyntaxError

    source = path.read_text(encoding="utf-8", errors="replace")
    errors = check_multiline_comments(path, source)
    errors.extend(check_markup_conventions(path, source))
    errors.extend(check_list_loops(path, source))

    try:
        compiled = engine.from_string(source)
    except TemplateSyntaxError as err:
        errors.append(f"{path}: {err}")
        return errors
    except Exception as err:
        errors.append(f"{path}: {type(err).__name__}: {err}")
        return errors

    own_name = template_name(path)
    if own_name and own_name in constant_template_names(compiled):
        errors.append(
            f"{path}: template includes or extends itself ('{own_name}'), which "
            "recurses until RecursionError at render time. If this is meant as "
            "usage documentation, put it inside {% comment %}...{% endcomment %}."
        )
    return errors


def build_engine():
    """A bare template Engine: no settings module, no database, no game dir."""
    import django
    from django.apps import apps as django_apps
    from django.conf import settings
    from django.template import Engine
    from django.template.backends.django import get_installed_libraries

    installed = []
    for app in CANDIDATE_APPS:
        try:
            __import__(app)
        except ImportError:
            continue
        installed.append(app)

    if not settings.configured:
        settings.configure(DEBUG=False, INSTALLED_APPS=installed, USE_TZ=True)
    if not django_apps.ready:
        django.setup()
    return Engine(libraries=get_installed_libraries())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="templates to check (default: all)")
    parser.add_argument(
        "--require-django",
        action="store_true",
        help="fail instead of skipping when Django is not importable",
    )
    args = parser.parse_args(argv)

    try:
        engine = build_engine()
    except ImportError:
        message = "check_templates: Django is not importable, skipping template sweep."
        print(message, file=sys.stderr)
        return 1 if args.require_django else 0

    errors = []
    templates = iter_templates(args.paths)
    for path in templates:
        errors.extend(check_template(path, engine))

    for error in errors:
        print(error)
    if errors:
        summary = f"{len(errors)} problem(s) in {len(templates)} template(s)."
        print(f"\ncheck_templates: {summary}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
