"""Compile every Django template in the repo and fail on the syntax-error class.

Run as a pre-commit hook (receives candidate paths as positional arguments) or
with no arguments to sweep the whole tree.

A broken template is invisible to the test suite unless a test actually
*renders* the page it belongs to: building a view's context compiles nothing,
so a page can be a guaranteed 500 while its view tests stay green. This sweep
compiles every template unconditionally, so the whole class is caught at commit
time rather than by a visitor.

Three checks, each covering a bug this repo has actually shipped:

1.  **It compiles at all.** Catches unbalanced tags, unknown filters, leading-
    underscore variable lookups (``{{ board._post_count }}``), and tags nested
    inside a quoted argument (``with cancel_url="{% url 'x' %}"``) -- the latter
    reads naturally but the tokenizer ends the outer tag at the first ``%}``.

2.  **No multi-line ``{# ... #}``.** Django's tokenizer regex has no DOTALL, so
    a comment spanning lines is not a comment: its contents are parsed as live
    template source. A usage example inside one becomes a real ``{% include %}``.

3.  **No template includes itself.** The usual way check 2 turns fatal -- a
    partial documenting its own usage recursed until RecursionError.

Compilation needs Django, but nothing else: no settings module, no database, no
game directory. If Django is not importable the sweep prints a hint and exits 0,
matching the anonymity guard's "don't block a bare clone" behaviour; pass
``--require-django`` (as CI does) to make that a hard failure instead.
"""

from __future__ import annotations

import argparse
import re
import sys
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
