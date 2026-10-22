# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Saved outfits replace gear together and preserve every existing wear safeguard."""

from unittest.mock import patch

from evennia_rp_chargen import abilities, locks
from evennia_rp_chargen import services as chargen
from evennia_rp_chargen.services import ChargenError

from evennia_rp_equipment import outfits, services
from evennia_rp_equipment.display import worn_items
from evennia_rp_equipment.requirements import PIPS, Requirement
from evennia_rp_equipment.services import GearError

from .base import GearTest


class OutfitTests(GearTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char2, brawn="Mid++")
        self.axe = self.make_item(self.char2, "axe", "Brawn +2")
        self.cloak = self.make_item(self.char2, "cloak", slot="cloak")
        self.hat = self.make_item(self.char2, "hat", slot="head")
        services.wear(self.char2, self.axe)
        services.wear(self.char2, self.cloak)
        outfits.save(self.char2, "Expedition")
        services.remove(self.char2, self.axe)
        services.remove(self.char2, self.cloak)
        services.wear(self.char2, self.hat)

    def assert_unchanged(self, action, message):
        with (
            patch.object(self.char2, "msg") as own,
            patch.object(self.char1, "msg") as room,
            self.assertRaisesMessage(GearError, message),
        ):
            action()
        self.assertEqual(worn_items(self.char2), [self.hat])
        own.assert_not_called()
        room.assert_not_called()

    def test_replaces_all_gear_and_guards_the_new_build_commitment(self):
        with patch.object(self.char1, "msg") as room:
            self.assertEqual(outfits.apply(self.char2, "expedition"), [])
        self.assertEqual(set(worn_items(self.char2)), {self.cloak, self.axe})
        self.assertIn("changes outfits", str(room.call_args))
        with self.assertRaisesMessage(ChargenError, "held by your axe"):
            chargen.set_edge(self.char2, "brawn", 1)
        outfits.apply(self.char2, "EXPEDITION")  # retained gear is harmless

    def test_missing_transferred_and_deleted_references_refuse_the_entire_set(self):
        for destination in (self.room1, self.char1):
            self.cloak.move_to(destination, quiet=True)
            self.assert_unchanged(
                lambda: outfits.apply(self.char2, "Expedition"), "no longer carry"
            )
        self.cloak.delete()
        self.assert_unchanged(lambda: outfits.apply(self.char2, "Expedition"), "no longer carry")

    def test_changed_pips_and_unknown_requirements_refuse_before_any_writes(self):
        chargen.set_edge(self.char2, "brawn", 1)
        self.assert_unchanged(lambda: outfits.apply(self.char2, "Expedition"), "needs Brawn ++")
        self.axe.requirement_data = [Requirement(PIPS, stat="gone", count=1).to_dict()]
        self.assert_unchanged(lambda: outfits.apply(self.char2, "Expedition"), "no longer has")

    def test_owned_but_unequipped_ability_refuses_and_unowned_only_notifies(self):
        services.add_requirement(self.char2, self.cloak, "ability Domain Expertise/Riddles")
        abilities.acquire(self.char2, "domain expertise", "riddles")
        abilities.unequip(self.char2, "domain expertise", "riddles")
        self.assert_unchanged(lambda: outfits.apply(self.char2, "Expedition"), "equipped")
        abilities.revoke(self.char2, "domain expertise", "riddles")
        notices = outfits.apply(self.char2, "Expedition")
        self.assertIn("aren't fully attuned to cloak", notices[0])

    def test_frozen_build_refuses_even_an_empty_outfit_and_staff_have_no_override(self):
        locks.lock(self.char2)
        self.assert_unchanged(
            lambda: outfits.apply(self.char2, "Expedition"), "locked for the scene"
        )
        services.wear(self.char1, self.make_item(self.char1, "staff hat"))
        outfits.save(self.char1, "staff")
        self.make_sheet(self.char1)
        locks.lock(self.char1)
        with self.assertRaisesMessage(GearError, "locked for the scene"):
            outfits.apply(self.char1, "staff")
        locks.unlock(self.char2)
        services.remove(self.char2, self.hat)
        outfits.save(self.char2, "Empty")
        services.wear(self.char2, self.hat)
        locks.lock(self.char2)
        self.assert_unchanged(lambda: outfits.apply(self.char2, "Empty"), "locked for the scene")

    def test_empty_sets_remove_everything_and_free_the_build(self):
        services.remove(self.char2, self.hat)
        outfits.save(self.char2, "Empty")
        outfits.apply(self.char2, "Expedition")
        outfits.apply(self.char2, "empty")
        self.assertEqual(worn_items(self.char2), [])
        chargen.set_edge(self.char2, "brawn", 0)

    def test_names_are_private_case_insensitive_and_saved_as_references(self):
        self.axe.key = "renamed axe"
        self.assertIn(self.axe, [item for _, item in outfits.items(self.char2, "Expedition")])
        self.assertEqual(outfits.saved(self.char1), {})
        with self.assertRaisesMessage(GearError, "no outfit named"):
            outfits.apply(self.char1, "Expedition")
        outfits.save(self.char2, "EXPEDITION")
        self.assertEqual(len(outfits.saved(self.char2)), 1)
        self.assertEqual(outfits.items(self.char2, "expedition"), [(self.hat.pk, self.hat)])
        outfits.delete(self.char2, "eXpedition")
        self.assertEqual(outfits.saved(self.char2), {})
        for name in ("", "x" * 81):
            with self.assertRaises(GearError):
                outfits.save(self.char2, name)

    def test_rollback_restores_tags_and_caches_without_announcing_a_partial_change(self):
        with (
            patch.object(self.cloak.tags, "add", side_effect=RuntimeError("storage failure")),
            patch.object(self.char2, "msg") as own,
            patch.object(self.char1, "msg") as room,
            self.assertRaisesMessage(RuntimeError, "storage failure"),
        ):
            outfits.apply(self.char2, "Expedition")
        self.assertEqual(worn_items(self.char2), [self.hat])
        own.assert_not_called()
        room.assert_not_called()
