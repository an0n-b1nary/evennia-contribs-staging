# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Parsing, describing and evaluating requirements against a real chargen build."""

from __future__ import annotations

from evennia_rp_chargen import abilities
from evennia_rp_chargen import services as chargen

from evennia_rp_equipment.requirements import (
    ABILITY,
    FLAW,
    MET,
    PIPS,
    UNATTUNED,
    UNKNOWN,
    UNMET,
    WEAKNESS,
    Requirement,
    RequirementError,
    describe,
    parse,
    status,
)

from .base import GearTest


class ParseTests(GearTest):
    def test_stat_forms(self):
        self.assertEqual(parse("Brawn +2"), Requirement(PIPS, stat="brawn", count=2))
        self.assertEqual(parse("brawn ++"), Requirement(PIPS, stat="brawn", count=2))
        self.assertEqual(parse("str+1"), Requirement(PIPS, stat="brawn", count=1))
        self.assertEqual(parse("Charm -1"), Requirement(WEAKNESS, stat="charm", count=1))
        self.assertEqual(parse("Charm --"), Requirement(WEAKNESS, stat="charm", count=2))

    def test_ability_and_flaw_forms(self):
        self.assertEqual(
            parse("ability Domain Expertise: Riddles"),
            Requirement(ABILITY, ability="domain-expertise", tag="riddles"),
        )
        self.assertEqual(parse("ability lucky"), Requirement(ABILITY, ability="lucky"))
        self.assertEqual(
            parse("flaw domain ineptitude: climbing"),
            Requirement(FLAW, ability="domain-ineptitude", tag="climbing"),
        )

    def test_refusals(self):
        for text, message in (
            ("", "Give a requirement like"),
            ("Brawn", "Give a requirement like"),
            ("Luck +1", "luck"),
            ("Brawn +4", "nobody could wear it"),
            ("Brawn +0", "at least one pip"),
            ("ability Domain Ineptitude: Riddles", "is a flaw"),
            ("flaw Lucky", "isn't a flaw"),
            ("ability Domain Expertise", "Which domain?"),
            ("ability Lucky: Riddles", "isn't chosen per tag"),
            ("ability Domain Expertise: Fire", "fire"),
        ):
            with self.subTest(text=text), self.assertRaises(RequirementError) as caught:
                parse(text)
            self.assertIn(message.lower(), str(caught.exception).lower())

    def test_round_trip_through_storage(self):
        for req in (
            parse("Brawn +2"),
            parse("ability Domain Expertise: Riddles"),
            parse("flaw Domain Ineptitude: Climbing"),
        ):
            self.assertEqual(Requirement.from_dict(req.to_dict()), req)


class DescribeTests(GearTest):
    def test_descriptions(self):
        self.assertEqual(describe(parse("Brawn +2")), "Brawn ++")
        self.assertEqual(describe(parse("Charm -1")), "Charm -")
        self.assertEqual(
            describe(parse("ability Domain Expertise: Riddles")),
            "Domain Expertise: Riddles equipped",
        )
        self.assertEqual(
            describe(parse("flaw Domain Ineptitude: Climbing")),
            "the flaw Domain Ineptitude: Climbing",
        )

    def test_unknown_keys_are_named_not_hidden(self):
        self.assertEqual(
            describe(Requirement(PIPS, stat="luck", count=1)), "an unknown stat (luck)"
        )
        self.assertEqual(
            describe(Requirement(ABILITY, ability="gone", tag="riddles")),
            "an unknown ability (gone: riddles)",
        )


class StatusTests(GearTest):
    def test_stat_requirements(self):
        self.make_sheet(self.char1, brawn="Mid++", charm="Low-")
        self.assertEqual(status(self.char1, parse("Brawn +2")), MET)
        self.assertEqual(status(self.char1, parse("Brawn +3")), UNMET)
        self.assertEqual(status(self.char1, parse("Charm -1")), MET)
        self.assertEqual(status(self.char2, parse("Brawn +1")), UNMET)  # no sheet
        self.assertEqual(status(self.char1, Requirement(PIPS, stat="luck", count=1)), UNKNOWN)

    def test_ability_requirements(self):
        self.make_sheet(self.char1)
        req = parse("ability Domain Expertise: Riddles")
        self.assertEqual(status(self.char1, req), UNATTUNED)
        abilities.acquire(self.char1, "domain expertise", "riddles")
        self.assertEqual(status(self.char1, req), MET)
        abilities.unequip(self.char1, "domain expertise", "riddles")
        self.assertEqual(status(self.char1, req), UNMET)
        other_tag = parse("ability Domain Expertise: Climbing")
        self.assertEqual(status(self.char1, other_tag), UNATTUNED)

    def test_flaw_requirements(self):
        self.make_sheet(self.char1)
        req = parse("flaw Domain Ineptitude: Climbing")
        self.assertEqual(status(self.char1, req), UNMET)
        abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.assertEqual(status(self.char1, req), MET)

    def test_draft_sheets_are_checked_too(self):
        self.make_sheet(self.char1, finalize=False, brawn="Mid+")
        self.assertEqual(status(self.char1, parse("Brawn +1")), MET)
        chargen.set_edge(self.char1, "brawn", 0)
        self.assertEqual(status(self.char1, parse("Brawn +1")), UNMET)
