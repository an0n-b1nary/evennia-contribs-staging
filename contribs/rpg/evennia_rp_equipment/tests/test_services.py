# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Making, editing, sealing, wearing and removing; worn items staying put."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings
from evennia_rp_chargen import abilities, locks

from evennia_rp_equipment import services
from evennia_rp_equipment.requirements import PIPS, Requirement
from evennia_rp_equipment.services import GearError

from .base import GearTest


class MakingTests(GearTest):
    def test_make_puts_a_plain_item_in_the_makers_hands(self):
        item = services.make(self.char1, "Cursed Axe", slot="Weapon")
        self.assertEqual(item.location, self.char1)
        self.assertEqual((item.maker_id, item.maker_name), (self.char1.id, self.char1.key))
        self.assertEqual(item.slot, "weapon")
        self.assertFalse(item.sealed)
        self.assertFalse(item.is_worn)
        self.assertEqual(item.get_requirements(), [])

    def test_names_are_required(self):
        with self.assertRaisesMessage(GearError, "Give the item a name"):
            services.make(self.char1, "  ")

    @override_settings(RP_EQUIPMENT_ITEM_CAP=2)
    def test_the_cap_counts_items_still_in_the_world(self):
        first = services.make(self.char1, "one")
        services.make(self.char1, "two")
        with self.assertRaisesMessage(GearError, "most allowed"):
            services.make(self.char1, "three")
        first.move_to(self.char2, quiet=True, move_type="give")  # given away: still counts
        with self.assertRaisesMessage(GearError, "most allowed"):
            services.make(self.char1, "three")
        services.destroy(self.char2, first)
        services.make(self.char1, "three")
        self.assertEqual(services.made_count(self.char1), 2)

    @override_settings(RP_EQUIPMENT_ITEM_CAP=None)
    def test_no_cap(self):
        for n in range(25):
            services.make(self.char1, f"item {n}")


class EditingTests(GearTest):
    def setUp(self):
        super().setUp()
        self.item = services.make(self.char1, "cloak", slot="body")

    def test_the_maker_edits_prose_and_slot(self):
        services.set_desc(self.char1, self.item, "Deep indigo wool.")
        services.set_worn_line(self.char1, self.item, "a cloak of deep indigo")
        services.set_slot(self.char1, self.item, "Back")
        self.assertEqual(self.item.db.desc, "Deep indigo wool.")
        self.assertEqual(self.item.get_worn_line(), "a cloak of deep indigo")
        self.assertEqual(self.item.slot, "back")

    def test_requirements_replace_by_stat_and_refuse_duplicates(self):
        services.add_requirement(self.char1, self.item, "Brawn +1")
        services.add_requirement(self.char1, self.item, "Brawn +2")
        services.add_requirement(self.char1, self.item, "Brawn -1")
        self.assertEqual(
            [(r.kind, r.count) for r in self.item.get_requirements()],
            [("pips", 2), ("weakness", 1)],
        )
        with self.assertRaisesMessage(GearError, "already requires Brawn ++"):
            services.add_requirement(self.char1, self.item, "brawn ++")
        removed = services.remove_requirement(self.char1, self.item, 1)
        self.assertEqual(removed, Requirement(PIPS, stat="brawn", count=2))
        with self.assertRaisesMessage(GearError, "no requirement 5"):
            services.remove_requirement(self.char1, self.item, 5)

    def test_bad_requirement_text_is_a_gear_error(self):
        with self.assertRaisesMessage(GearError, "Give a requirement like"):
            services.add_requirement(self.char1, self.item, "nonsense")

    def test_only_the_maker_edits(self):
        self.item.move_to(self.char2, quiet=True, move_type="give")
        with self.assertRaisesMessage(GearError, "Only its maker"):
            services.set_desc(self.char2, self.item, "Mine now.")

    def test_changing_hands_seals_it_for_good(self):
        self.item.move_to(self.char2, quiet=True, move_type="give")
        self.item.move_to(self.char1, quiet=True, move_type="give")
        self.assertTrue(self.item.sealed)
        with self.assertRaisesMessage(GearError, "changed hands"):
            services.add_requirement(self.char1, self.item, "Brawn +1")

    def test_dropping_and_picking_it_back_up_doesnt_seal(self):
        self.item.move_to(self.room1, quiet=True, move_type="drop")
        self.item.move_to(self.char1, quiet=True, move_type="get")
        self.assertFalse(self.item.sealed)

    def test_you_must_carry_it(self):
        self.item.move_to(self.room1, quiet=True, move_type="drop")
        with self.assertRaisesMessage(GearError, "aren't carrying"):
            services.set_slot(self.char1, self.item, "head")

    def test_requirements_dont_change_while_worn(self):
        services.wear(self.char1, self.item)
        with self.assertRaisesMessage(GearError, "before changing what it requires"):
            services.add_requirement(self.char1, self.item, "Brawn +1")
        with self.assertRaisesMessage(GearError, "before changing what it requires"):
            services.remove_requirement(self.char1, self.item, 1)


class WearingTests(GearTest):
    def test_wear_and_remove_announce_to_the_room(self):
        item = self.make_item(self.char1, "cloak", slot="body")
        with patch.object(self.char2, "msg") as seen:
            notices = services.wear(self.char1, item)
        self.assertEqual(notices, [])
        self.assertTrue(item.is_worn)
        self.assertEqual(item.wearer, self.char1)
        self.assertIn("puts on", str(seen.call_args))
        with patch.object(self.char2, "msg") as seen:
            services.remove(self.char1, item)
        self.assertFalse(item.is_worn)
        self.assertIn("takes off", str(seen.call_args))

    def test_twice_and_not_worn(self):
        item = self.make_item(self.char1)
        services.wear(self.char1, item)
        with self.assertRaisesMessage(GearError, "already wearing"):
            services.wear(self.char1, item)
        services.remove(self.char1, item)
        with self.assertRaisesMessage(GearError, "aren't wearing"):
            services.remove(self.char1, item)

    def test_unmet_requirements_refuse(self):
        self.make_sheet(self.char1, brawn="Mid+")
        item = self.make_item(self.char1, "axe", "Brawn +2", "flaw Domain Ineptitude: Riddles")
        with self.assertRaisesMessage(
            GearError, "Wearing axe needs Brawn ++, the flaw Domain Ineptitude: Riddles."
        ):
            services.wear(self.char1, item)
        self.assertFalse(item.is_worn)

    def test_an_unowned_ability_only_means_not_attuned(self):
        self.make_sheet(self.char1)
        item = self.make_item(self.char1, "staff", "ability Domain Expertise: Riddles")
        notices = services.wear(self.char1, item)
        self.assertTrue(item.is_worn)
        self.assertIn("aren't fully attuned", notices[0])

    def test_an_owned_but_unequipped_ability_refuses(self):
        self.make_sheet(self.char1)
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.unequip(self.char1, "domain expertise", "riddles")
        item = self.make_item(self.char1, "staff", "ability Domain Expertise: Riddles")
        with self.assertRaisesMessage(
            GearError, "Wearing staff needs Domain Expertise: Riddles equipped."
        ):
            services.wear(self.char1, item)

    def test_requirements_this_game_no_longer_has_refuse(self):
        item = self.make_item(self.char1)
        item.requirement_data = [Requirement(PIPS, stat="luck", count=1).to_dict()]
        with self.assertRaisesMessage(GearError, "no longer has"):
            services.wear(self.char1, item)

    def test_gear_freezes_with_the_build(self):
        self.make_sheet(self.char1)
        cloak = self.make_item(self.char1, "cloak")
        hat = self.make_item(self.char1, "hat")
        services.wear(self.char1, hat)
        locks.lock(self.char1)
        with self.assertRaisesMessage(GearError, "locked for the scene"):
            services.wear(self.char1, cloak)
        with self.assertRaisesMessage(GearError, "locked for the scene"):
            services.remove(self.char1, hat)
        locks.unlock(self.char1)
        services.wear(self.char1, cloak)

    def test_drafts_and_sheetless_characters_never_freeze(self):
        item = self.make_item(self.char2)
        locks.lock(self.char2)  # no sheet at all
        services.wear(self.char2, item)


class StayingPutTests(GearTest):
    def setUp(self):
        super().setUp()
        self.item = self.make_item(self.char1, "cloak")
        services.wear(self.char1, self.item)

    def test_worn_items_refuse_drop_give_and_get(self):
        with patch.object(self.char1, "msg") as told:
            self.assertFalse(self.item.at_pre_drop(self.char1))
            self.assertFalse(self.item.at_pre_give(self.char1, self.char2))
        self.assertIn("Remove", told.call_args.args[0])
        self.assertFalse(self.item.at_pre_get(self.char2))
        for move_type in ("drop", "give", "get"):
            self.assertFalse(self.item.move_to(self.room1, quiet=True, move_type=move_type))
        self.assertEqual(self.item.location, self.char1)

    def test_worn_items_cant_be_destroyed(self):
        with self.assertRaisesMessage(GearError, "Remove"):
            services.destroy(self.char1, self.item)

    def test_a_staff_teleport_takes_it_off(self):
        self.assertTrue(self.item.move_to(self.room1, quiet=True, move_type="teleport"))
        self.assertFalse(self.item.is_worn)
