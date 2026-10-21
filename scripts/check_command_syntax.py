# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Hold contrib commands to the syntax ceiling in CODING_STYLE.md.

No command is harder to type than ``+command/switch target=value``. The sweep
reads source without importing it, so it needs neither Django nor a game:

1.  **Stacked switches** anywhere a player could read them: ``+cmd/a/b`` or
    ``+cmd/a[/b]`` in contrib source, guides, READMEs and templates, and
    ``/a/b`` continuations inside a command's help.
2.  **Usage lines** in a command's help: no ``;``, ``~`` or spaced `` | ``
    separators, no ``:`` sub-separators, no JSON, one ``=`` at most, no
    ``[,option]`` stacking and no run of positional placeholders before the
    ``=`` (``<property> <character>`` instead of ``<property>=<character>``).
3.  **Semicolon parsing:** a command module never splits or partitions input
    on ``;``.

Changelogs (history) and tests (which assert old forms are refused) are not
scanned. Today's offenders are listed in ``command_syntax_allowlist.txt``,
one ``<contrib> <rule> <subject>`` per line. Each syntax PR deletes its lines;
an entry that no longer matches anything fails the sweep, so the list only
shrinks. ``--print-keys`` lists every current finding's key.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRIBS_ROOT = REPO_ROOT / "contribs"
ALLOWLIST = Path(__file__).resolve().parent / "command_syntax_allowlist.txt"
TEXT_SUFFIXES = {".py", ".md", ".html", ".txt"}
SKIP_DIRS = {"__pycache__", "migrations", "tests", "build", "static"}
SKIP_NAMES = {"CHANGELOG.md"}

# Permanent, documented exceptions: (contrib, rule, subject). Staff-only
# runtime settings take JSON values by design.
EXEMPT = {("evennia_links", "json", "+runtime")}

SWITCH = r"\[?/(?:<[\w -]+>|[A-Za-z][\w|-]*)\]?"
STACKED = re.compile(rf"\+[A-Za-z][\w-]*(?:{SWITCH}){{2,}}")
HELP_STACKED = re.compile(rf"(?:^|[\s(])/[A-Za-z][\w-]*(?:{SWITCH})+")
# A semicolon after a command form (a placeholder or '=') in a prose help line.
PROSE_SEMICOLON = re.compile(r"(?:^|\s)(?:\+[A-Za-z]|/[A-Za-z])[^;]*[<=][^;]*;")
DESCRIPTION = re.compile(r"\s{2,}|\s-\s|\s\(")
PLACEHOLDER = re.compile(r"<[^>]*>")
# Give-style amounts ("53 scales") are one argument: <qty> <item>.
AMOUNT = re.compile(r"<(?:qty|quantity|amount|amt|count|number|n)>\s+(?=<)", re.IGNORECASE)
OPTIONAL = re.compile(r"\[[^\]]*\]")
COLON = re.compile(r"\[:|[\w>\]]\s*:\s*[<\w\[]")
OPTION_STACK = re.compile(r"\[\s*,(?![^\]]*(?:\.\.\.|…))")
JSON = re.compile(r"\bJSON\b|=\s*\{")
RULES = {
    "stacked-switch": "more than one switch; use one switch or a companion command",
    "semicolon": "';' separator; split the fields into switches or commands",
    "tilde": "'~' separator; use a trailing '# comment' instead",
    "pipe": "' | ' separator; one value per command",
    "colon": "':' sub-separator; use target/field=value or '53 scales'",
    "json": "JSON on the command line; set one field per command",
    "nested-equals": "more than one '='; '=' relates one target to one value",
    "option-stack": "'[,option]' stacking; make the option its own command",
    "positional-chain": "several positional arguments; use <target>=<value>",
    "semicolon-parse": "input split on ';'",
}


@dataclass(frozen=True)
class Finding:
    """One rule violation, keyed for the allowlist by contrib, rule and subject."""

    path: Path
    line: int
    contrib: str
    rule: str
    subject: str
    text: str

    @property
    def key(self) -> str:
        return f"{self.contrib} {self.rule} {self.subject}"

    def __str__(self) -> str:
        where = (
            self.path.relative_to(REPO_ROOT) if self.path.is_relative_to(REPO_ROOT) else self.path
        )
        return f"{where}:{self.line}: {self.rule}: {RULES[self.rule]}\n    {self.text.strip()}"


def contrib_of(path: Path, root: Path = CONTRIBS_ROOT) -> str:
    """Return the contrib directory name (``evennia_x``) a path belongs to."""
    parts = path.relative_to(root).parts
    return parts[1] if len(parts) > 2 else parts[0]


def scanned(path: Path, root: Path = CONTRIBS_ROOT) -> bool:
    """Whether the sweep reads this file: shipped text, not tests or history."""
    rel = path.relative_to(root)
    return (
        path.suffix in TEXT_SUFFIXES
        and path.name not in SKIP_NAMES
        and not path.name.startswith("test")
        and not SKIP_DIRS.intersection(rel.parts[:-1])
    )


def literal(node):
    """Return a literal value, or None when the expression is not one."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


def command_classes(tree: ast.Module):
    """Yield (class node, key, aliases) for each command class in a module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        attrs, methods = {}, set()
        for statement in node.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Name):
                    attrs[target.id] = literal(statement.value)
            elif isinstance(statement, ast.FunctionDef):
                methods.add(statement.name)
        key = attrs.get("key")
        bases = " ".join(ast.unparse(base) for base in node.bases)
        if (
            isinstance(key, str)
            and "at_cmdset_creation" not in methods
            and "CmdSet" not in bases
            and ("func" in methods or "Command" in bases or "Cmd" in bases)
        ):
            aliases = attrs.get("aliases")
            aliases = (
                [a for a in aliases if isinstance(a, str)] if isinstance(aliases, list) else []
            )
            yield node, key, aliases


def usage_form(line: str, names: list[str]) -> str | None:
    """Return the syntax part of a help line that shows a command form, else None."""
    text = line.strip().removeprefix("Usage:").strip()
    first = text.split(maxsplit=1)[0] if text else ""
    if first.startswith("/"):
        # A help line may continue with bare switches; prose may also start with one.
        rest = text.split()[1:2]
        if "=" not in first and not (rest and rest[0][0] in "<[#="):
            return None
    elif not any(first == name or first.startswith((f"{name}/", f"{name}[")) for name in names):
        return None
    for name in sorted(names, key=len, reverse=True):
        if first.startswith(name) and not name[0].isalnum():
            # A punctuation alias (semipose's ';') is the command word itself.
            text = text[len(name) :]
            break
    return DESCRIPTION.split(text, maxsplit=1)[0]


def positional_chain(form: str) -> bool:
    """Whether two placeholders sit next to each other before the '='."""
    words = OPTIONAL.sub("[]", PLACEHOLDER.sub("<>", AMOUNT.sub("", form))).split()[1:]
    run = longest = 0
    for word in words:
        head = word.split("=", 1)[0].strip("[]")
        if (head and head[0] in "<[#") or head.startswith("<>"):
            run += 1
            longest = max(longest, run)
        elif head:
            run = 0
        if "=" in word:
            break
    return longest > 1


def usage_rules(form: str) -> list[str]:
    """Return the usage-line rules a command form breaks."""
    rules = []
    if ";" in form:
        rules.append("semicolon")
    if "~" in form:
        rules.append("tilde")
    if " | " in form:
        rules.append("pipe")
    if JSON.search(form):
        rules.append("json")
    if COLON.search(form):
        rules.append("colon")
    if form.count("=") > 1:
        rules.append("nested-equals")
    if OPTION_STACK.search(form):
        rules.append("option-stack")
    if positional_chain(form):
        rules.append("positional-chain")
    return rules


def semicolon_parses(node: ast.AST):
    """Yield calls that split or partition on a ';' literal."""
    for call in ast.walk(node):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"split", "rsplit", "partition", "rpartition"}
            and any(
                isinstance(sub, ast.Constant) and sub.value == ";"
                for arg in call.args
                for sub in ast.walk(arg)
            )
        ):
            yield call


def check_module(path: Path, source: str, contrib: str) -> list[Finding]:
    """Check a Python module's command help and its parsing."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    commands = list(command_classes(tree))
    if not commands:
        return []
    lines = source.splitlines()
    findings = []
    for node, key, aliases in commands:
        doc = ast.get_docstring(node, clean=False)
        if doc:
            start = node.body[0].lineno
            names = [key, *aliases]
            for offset, line in enumerate(doc.splitlines()):
                lineno = start + offset
                form = usage_form(line, names)
                rules = usage_rules(form) if form is not None else []
                if form is None and PROSE_SEMICOLON.search(line):
                    rules.append("semicolon")
                if HELP_STACKED.search(line) and not STACKED.search(line):
                    rules.append("stacked-switch")
                findings += [Finding(path, lineno, contrib, r, key, line) for r in rules]
        for call in semicolon_parses(node):
            text = lines[call.lineno - 1]
            findings.append(Finding(path, call.lineno, contrib, "semicolon-parse", key, text))
    inside = {id(call) for node, _, _ in commands for call in semicolon_parses(node)}
    for call in semicolon_parses(tree):
        if id(call) not in inside:
            text = lines[call.lineno - 1]
            findings.append(Finding(path, call.lineno, contrib, "semicolon-parse", path.name, text))
    return findings


def check_file(path: Path, root: Path = CONTRIBS_ROOT) -> list[Finding]:
    """Return every finding in one contrib file."""
    contrib = contrib_of(path, root)
    source = path.read_text(encoding="utf-8")
    findings = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for match in STACKED.finditer(line):
            subject = re.split(r"[/\[]", match.group())[0]
            findings.append(Finding(path, lineno, contrib, "stacked-switch", subject, line))
    if path.suffix == ".py":
        findings += check_module(path, source, contrib)
    return [f for f in findings if (f.contrib, f.rule, f.subject) not in EXEMPT]


def sweep(root: Path = CONTRIBS_ROOT) -> list[Finding]:
    """Check every shipped contrib file under root."""
    return [
        finding
        for path in sorted(root.rglob("*"))
        if path.is_file() and scanned(path, root)
        for finding in check_file(path, root)
    ]


def read_allowlist(path: Path = ALLOWLIST) -> set[str]:
    """Read allowlist keys, ignoring blank lines and '#' comments."""
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            keys.add(" ".join(line.split()))
    return keys


def main(
    argv: list[str] | None = None, root: Path = CONTRIBS_ROOT, allowlist: Path = ALLOWLIST
) -> int:
    """Report findings outside the allowlist and allowlist entries with no finding."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print-keys", action="store_true", help="list every finding's key")
    args = parser.parse_args(argv)
    findings = sweep(root)
    if args.print_keys:
        print("\n".join(sorted({finding.key for finding in findings})))
        return 0
    allowed = read_allowlist(allowlist)
    new = [finding for finding in findings if finding.key not in allowed]
    stale = sorted(allowed - {finding.key for finding in findings})
    for finding in new:
        print(finding, file=sys.stderr)
    for key in stale:
        print(f"{allowlist.name}: '{key}' matches nothing; delete the line.", file=sys.stderr)
    if new or stale:
        print(
            f"\nCommand syntax: {len(new)} new finding(s), {len(stale)} stale allowlist "
            "entr(ies). See 'Command syntax' in CODING_STYLE.md.",
            file=sys.stderr,
        )
        return 1
    print(f"Command syntax checks passed ({len(allowed)} allowlisted offenders remain).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
