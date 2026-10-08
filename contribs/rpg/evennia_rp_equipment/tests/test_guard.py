# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Worn gear refuses the build changes it depends on, through chargen's real services."""

from __future__ import annotations

from evennia_rp_chargen import abilities
from evennia_rp_chargen import services as chargen
from evennia_rp_chargen.guards import build_change_requested
from evennia_rp_chargen.services import ChargenError

from evennia_rp_equipment import services
from evennia_rp_equipment.guard import DISPATCH_UID

from .base import GearTest


class ConnectionTests(GearTest):
    def test_ready_connected_the_guard(self):
        self.assertTrue(build_change_requested.has_listeners())
        uids = [entry[0][0] for entry in build_change_requested.receivers]
        self.assertIn(DISPATCH_UID, uids)


class PipGuardTests(GearTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char1, brawn="Mid++", charm="Low-")
        self.axe = self.make_item(self.char1, "axe", "Brawn +2", "Charm -1")
        services.wear(self.char1, self.axe)

    def test_moving_required_pips_is_refused_while_worn(self):
        with self.assertRaisesMessage(
            ChargenError, "Brawn ++ is held by your axe. Take that off first."
        ):
            chargen.set_edge(self.char1, "brawn", 1)
        with self.assertRaisesMessage(ChargenError, "Charm - is held by your axe."):
            chargen.set_weakness(self.char1, "charm", 0)
        with self.assertRaisesMessage(ChargenError, "Brawn ++ is held by your axe."):
            chargen.clear_edge(self.char1)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_changes_that_keep_it_met_are_fine(self):
        chargen.set_edge(self.char1, "brawn", 3)
        chargen.set_edge(self.char1, "brawn", 2)
        chargen.set_edge(self.char1, "brains", 1)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_removing_the_gear_frees_the_build(self):
        services.remove(self.char1, self.axe)
        chargen.set_edge(self.char1, "brawn", 0)
        self.assertEqual(self.rating(self.char1), "Mid")

    def test_staff_are_refused_too_and_named_as_staff(self):
        message = f"Brawn ++ is held by {self.char1.key}'s axe. Take that off first."
        with self.assertRaisesMessage(ChargenError, message):
            chargen.staff_set_stat(self.char1, "brawn", "High", by=self.char2)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_carried_but_unworn_gear_doesnt_guard(self):
        services.remove(self.char1, self.axe)
        self.make_item(self.char1, "spare", "Brawn +2")
        chargen.set_edge(self.char1, "brawn", 0)


class AbilityGuardTests(GearTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char1)
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.staff = self.make_item(
            self.char1,
            "staff",
            "ability Domain Expertise: Riddles",
            "flaw Domain Ineptitude: Climbing",
        )
        services.wear(self.char1, self.staff)

    def test_unequipping_a_required_ability_is_refused(self):
        with self.assertRaisesMessage(
            ChargenError, "Domain Expertise: Riddles is held by your staff. Take that off first."
        ):
            abilities.unequip(self.char1, "domain expertise", "riddles")

    def test_shedding_a_required_flaw_is_refused(self):
        with self.assertRaisesMessage(
            ChargenError, "the flaw Domain Ineptitude: Climbing is held by your staff"
        ):
            abilities.remove_flaw(self.char1, "domain ineptitude", "climbing")

    def test_staff_revokes_are_refused(self):
        with self.assertRaisesMessage(ChargenError, f"is held by {self.char1.key}'s staff"):
            abilities.revoke(self.char1, "domain expertise", "riddles", by=self.char2)
        self.assertEqual(len(abilities.owned(self.char1)), 2)

    def test_other_tags_and_gains_are_unaffected(self):
        abilities.acquire(self.char1, "domain expertise", "climbing")
        abilities.unequip(self.char1, "domain expertise", "climbing")
        abilities.grant(self.char1, "lucky", by=self.char2)
        abilities.take_flaw(self.char1, "domain ineptitude", "riddles")
        abilities.remove_flaw(self.char1, "domain ineptitude", "riddles")


class AttunementTests(GearTest):
    def test_gaining_an_ability_while_unattuned_is_never_refused(self):
        self.make_sheet(self.char1)
        staff = self.make_item(self.char1, "staff", "ability Domain Expertise: Riddles")
        services.wear(self.char1, staff)
        copy, _ = abilities.acquire(self.char1, "domain expertise", "riddles")
        self.assertTrue(copy.equipped)
        # Now that it's met, it's guarded like any other requirement.
        with self.assertRaisesMessage(ChargenError, "is held by your staff"):
            abilities.unequip(self.char1, "domain expertise", "riddles")
