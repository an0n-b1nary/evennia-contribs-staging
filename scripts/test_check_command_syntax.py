# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Regressions for the command syntax sweep."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_command_syntax as checker

COMMAND = '''\
from evennia.commands.default.muxcommand import MuxCommand


class CmdProbe(MuxCommand):
    """Probe command.

    Usage:
{usage}
    """

    key = "+probe"
    aliases = ["+pr"]

    def func(self):
{body}
'''


class SyntaxSweep(unittest.TestCase):
    """Check fixture contribs without importing them."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.contrib = self.root / "game_systems" / "evennia_probe"
        self.contrib.mkdir(parents=True)

    def write(self, name, text):
        path = self.contrib / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def command(self, *usage, body="pass"):
        lines = "\n".join(f"      {line}" for line in usage)
        self.write("commands.py", COMMAND.format(usage=lines, body=f"        {body}"))

    def rules(self):
        return sorted({finding.rule for finding in checker.sweep(self.root)})

    def test_the_ceiling_passes(self):
        self.command(
            "+probe",
            "+probe <target>",
            "+probe/switch <target>=<value>     - Description (with: colon; and semicolon)",
            "+probe/give <qty> <item> to <character>",
            "+probe/list <eid>,<eid>,...",
            "+probe/note <thread>=<text> # comment",
            "+pr/read <board>/<post>",
            "+probe/stat <npc>/<stat>=<rating>",
        )
        self.assertEqual(self.rules(), [])

    def test_each_usage_rule_is_reported(self):
        cases = {
            "+probe/a <x>=<y>;<z>": "semicolon",
            "+probe/a <x>[~comment]": "tilde",
            "+probe/a <x>=<title> | <text>": "pipe",
            "+probe/a <x>=<amt>:<reason>": "colon",
            "+probe/a <ability>[: <tag>]": "colon",
            "+probe/a <x>=JSON": "json",
            '+probe/a Careful={"a":1}': "json",
            "+probe/a <x>=<y>[=<z>]": "nested-equals",
            "+probe/a <x>=<y>[,<note>]": "option-stack",
            "+probe/a <property> <character>": "positional-chain",
            "+probe/a <id> <revision>=<reason>": "positional-chain",
            "+probe/a/b <x>": "stacked-switch",
            "+probe/a[/b] <x>": "stacked-switch",
        }
        for usage, rule in cases.items():
            with self.subTest(usage=usage):
                self.command(usage)
                self.assertIn(rule, self.rules())

    def test_lists_and_bare_words_are_not_chains(self):
        self.command("+probe/a <x>=<y>[, <niche>...]", "+pr [stall/]item or lot = <price>")
        self.assertEqual(self.rules(), [])

    def test_dotted_addresses_with_trailing_comments_are_not_chains(self):
        self.command(
            "+probe/approve <id>.<revision> # <reason>",
            "+probe/approve #12.3 # <reason>",
            "+probe/withdraw <id>.<revision> [# reason]",
        )
        self.assertEqual(self.rules(), [])
        self.command("+probe/approve <id> <revision> # <reason>")
        self.assertIn("positional-chain", self.rules())

    def test_prose_help_lines(self):
        self.command(
            "/save stores everything worn; saving twice is fine.",
            "Use +probe/go; it is safe.",
        )
        self.assertEqual(self.rules(), [])
        self.command("Ban: +probe <account>=<reason>; /ip <CIDR>=<reason>.")
        self.assertEqual(self.rules(), ["semicolon"])
        self.command("/lift <account>; /lift/ip <CIDR>.")
        self.assertEqual(self.rules(), ["semicolon", "stacked-switch"])

    def test_punctuation_alias_is_the_command_word(self):
        text = COMMAND.replace('["+pr"]', '[";"]').format(usage="      ;<text>", body="pass")
        self.write("commands.py", text)
        self.assertEqual(self.rules(), [])

    def test_semicolon_parsing_in_command_modules_only(self):
        self.command("+probe", body='self.rhs.partition(";" if self.args else "=")')
        self.assertEqual(self.rules(), ["semicolon-parse"])
        self.write("storage.py", 'def parts(text):\n    return text.split(";")\n')
        self.assertEqual(
            {f.path.name for f in checker.sweep(self.root) if f.rule == "semicolon-parse"},
            {"commands.py"},
        )

    def test_stacked_switches_in_shipped_text(self):
        self.write("README.md", "Use `+probe/thread/new` and <code>+probe/post</code>.\n")
        self.write("templates/evennia_probe/x.html", "Try +probe/a/b here.\n")
        findings = checker.sweep(self.root)
        self.assertEqual(
            sorted((f.path.name, f.rule, f.subject) for f in findings),
            [("README.md", "stacked-switch", "+probe"), ("x.html", "stacked-switch", "+probe")],
        )

    def test_history_tests_and_cmdsets_are_skipped(self):
        self.write("CHANGELOG.md", "Removed +probe/a/b.\n")
        self.write("tests.py", '"+probe/a/b"\n')
        self.write("tests/test_x.py", '"+probe/a/b"\n')
        self.write(
            "cmdset.py",
            'from evennia import CmdSet\n\n\nclass ProbeSet(CmdSet):\n    """+probe/a <x> <y>"""\n'
            '\n    key = "probe"\n\n    def at_cmdset_creation(self):\n        pass\n',
        )
        self.assertEqual(checker.sweep(self.root), [])

    def test_exemptions(self):
        links = self.root / "base_systems" / "evennia_links"
        links.mkdir(parents=True)
        (links / "commands.py").write_text(
            COMMAND.replace("+probe", "+runtime").format(
                usage="      +runtime N=<JSON>", body="pass"
            ),
            encoding="utf-8",
        )
        self.assertEqual(checker.sweep(self.root), [])

    def test_allowlist_must_shrink(self):
        self.command("+probe/a/b <x>")
        allowlist = self.root / "allowlist.txt"
        run = lambda: self.run_main(allowlist)  # noqa: E731
        allowlist.write_text("", encoding="utf-8")
        self.assertEqual(run(), 1)
        allowlist.write_text("# comment\nevennia_probe   stacked-switch +probe\n", encoding="utf-8")
        self.assertEqual(run(), 0)
        allowlist.write_text(
            "evennia_probe stacked-switch +probe\nevennia_probe colon +probe\n", encoding="utf-8"
        )
        self.assertEqual(run(), 1)

    def run_main(self, allowlist):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return checker.main([], root=self.root, allowlist=allowlist)

    def test_repository_allowlist_is_current(self):
        self.assertEqual(self.run_repo(), 0)

    def run_repo(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return checker.main([])


if __name__ == "__main__":
    unittest.main()
