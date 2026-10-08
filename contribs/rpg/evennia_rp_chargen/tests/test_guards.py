# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Change guards: partners refuse build changes; partners freeze with the build lock."""

from __future__ import annotations

from decimal import Decimal

from django.test import override_settings

from evennia_rp_chargen import abilities, guards, locks, services
from evennia_rp_chargen.catalog import seed_catalog
from evennia_rp_chargen.commands import CmdChargen
from evennia_rp_chargen.guards import build_change_requested
from evennia_rp_chargen.models import AbilityTransaction, CharacterAbility
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.stats import StatHandler

from .base import ChargenCommandTest, ChargenTest
from .catalog_fixture import CATALOG_SETTINGS

AXE = "Your Cursed Axe needs this. Remove the axe first."


class GuardMixin:
    """Connects a guard that records every change and refuses kinds in `self.refuse`."""

    def setUp(self):
        super().setUp()
        self.asked = []
        self.refuse = {}
        self.connect(self.guard, "test.guard")

    def connect(self, receiver, uid):
        build_change_requested.connect(receiver, weak=False, dispatch_uid=uid)
        self.addCleanup(build_change_requested.disconnect, dispatch_uid=uid)

    def guard(self, sender, change, **kwargs):
        self.asked.append(change)
        return self.refuse.get(change.kind)

    def rating(self, character, stat="brawn"):
        return StatHandler(character).get(stat).display()


class RatingGuardTests(GuardMixin, ChargenTest):
    def test_pip_changes_are_asked_with_before_and_after(self):
        self.make_sheet(self.char1, brawn="Mid++")
        services.set_edge(self.char1, "brawn", 1)
        change = self.asked[-1]
        self.assertEqual((change.kind, change.stat.key), (guards.RATING, "brawn"))
        self.assertEqual((change.before.edge, change.after.edge), (2, 1))
        self.assertIsNone(change.by)

    def test_a_refused_pip_change_writes_nothing(self):
        self.make_sheet(self.char1, brawn="Mid++")
        self.refuse[guards.RATING] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            services.set_edge(self.char1, "brawn", 0)
        with self.assertRaisesMessage(ChargenError, AXE):
            services.clear_edge(self.char1)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_clearing_every_stat_is_all_or_nothing(self):
        self.make_sheet(self.char1, brawn="Mid++", brains="Mid+")
        self.connect(
            lambda sender, change, **kw: AXE if change.stat.key == "brains" else None,
            "test.brains",
        )
        with self.assertRaisesMessage(ChargenError, AXE):
            services.clear_edge(self.char1)
        self.assertEqual(self.rating(self.char1), "Mid ++")
        self.assertEqual(self.rating(self.char1, "brains"), "Mid +")

    def test_draft_rungs_and_clearing_are_asked(self):
        self.make_sheet(self.char1, finalize=False, brawn="Mid")
        self.refuse[guards.RATING] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            services.set_stat(self.char1, "brawn", "High")
        with self.assertRaisesMessage(ChargenError, AXE):
            services.clear_stat(self.char1, "brawn")
        self.assertIsNone(self.asked[-1].after)
        self.assertEqual(self.rating(self.char1), "Mid")

    def test_staff_edits_are_refused_too(self):
        self.make_sheet(self.char1, brawn="Mid++")
        self.refuse[guards.RATING] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            services.staff_set_stat(self.char1, "brawn", "High", by=self.char2)
        self.assertEqual(self.asked[-1].by, self.char2)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_the_sheet_rules_come_first(self):
        self.make_sheet(self.char1, brawn="Mid++")
        with self.assertRaisesMessage(ChargenError, "at most 3"):
            services.set_edge(self.char1, "brawn", 4)
        locks.lock(self.char1)
        with self.assertRaisesMessage(ChargenError, "locked for the scene"):
            services.set_edge(self.char1, "brawn", 1)
        with self.assertRaisesMessage(ChargenError, "locked for the scene"):
            services.clear_edge(self.char1)
        self.assertEqual(self.asked, [])


@override_settings(**CATALOG_SETTINGS)
class AbilityGuardTests(GuardMixin, ChargenTest):
    def setUp(self):
        super().setUp()
        seed_catalog()
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        self.asked.clear()

    def copy(self, name="Domain Expertise: Riddles"):
        return {c.display_name: c for c in abilities.owned(self.char1)}.get(name)

    def test_a_refused_unequip_keeps_it_equipped(self):
        self.refuse[guards.UNEQUIP] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.unequip(self.char1, "domain expertise", "riddles")
        self.assertTrue(self.copy().equipped)
        change = self.asked[-1]
        self.assertEqual((change.ability.key, change.tag.key), ("domain-expertise", "riddles"))
        self.assertEqual((change.copy, change.level), (self.copy(), 1))

    def test_a_refused_equip_leaves_it_unequipped(self):
        abilities.unequip(self.char1, "domain expertise", "riddles")
        self.refuse[guards.EQUIP] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.equip(self.char1, "domain expertise", "riddles")
        self.assertFalse(self.copy().equipped)

    def test_a_refused_purchase_spends_nothing(self):
        self.refuse[guards.ACQUIRE] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.acquire(self.char1, "domain expertise", "climbing", by=self.char1)
        self.assertIsNone(self.copy("Domain Expertise: Climbing"))
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(17))
        self.assertEqual(AbilityTransaction.objects.filter(kind="acquire").count(), 1)
        self.assertEqual((self.asked[-1].copy, self.asked[-1].level), (None, 1))

    def test_auto_equip_skips_quietly_when_a_guard_objects(self):
        self.refuse[guards.EQUIP] = AXE
        copy, _ = abilities.acquire(self.char1, "domain expertise", "climbing")
        self.assertFalse(copy.equipped)

    def test_a_refused_upgrade_spends_nothing(self):
        self.refuse[guards.UPGRADE] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.upgrade(self.char1, "domain expertise", "riddles")
        self.assertEqual(self.copy().level, 1)
        self.assertEqual(self.asked[-1].level, 2)
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(17))

    def test_flaws_are_asked(self):
        self.refuse[guards.TAKE_FLAW] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.refuse.clear()
        abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.refuse[guards.REMOVE_FLAW] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.remove_flaw(self.char1, "domain ineptitude")
        self.assertIsNotNone(self.copy("Domain Ineptitude: Climbing"))
        self.assertEqual(self.asked[-1].level, 0)

    def test_staff_grants_and_revokes_are_refused_too(self):
        self.refuse[guards.GRANT] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.grant(self.char1, "lucky", by=self.char2)
        self.assertIsNone(self.copy("Lucky"))
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.grant(self.char1, "domain expertise", "riddles", level=3, by=self.char2)
        self.assertEqual((self.asked[-1].copy, self.asked[-1].level), (self.copy(), 3))
        self.assertEqual(self.copy().level, 1)

        self.refuse[guards.REVOKE] = AXE
        with self.assertRaisesMessage(ChargenError, AXE):
            abilities.revoke(self.char1, "domain expertise", "riddles", refund=True, by=self.char2)
        self.assertTrue(CharacterAbility.objects.filter(pk=self.copy().pk).exists())
        self.assertEqual(self.asked[-1].by, self.char2)
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(17))


class GuardContractTests(GuardMixin, ChargenTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char1, brawn="Mid++")

    def test_every_refusal_is_shown_once(self):
        self.refuse[guards.RATING] = "Shared."
        self.connect(lambda sender, change, **kw: ["Other.", "Shared."], "test.second")
        with self.assertRaises(ChargenError) as caught:
            services.set_edge(self.char1, "brawn", 0)
        message = str(caught.exception)
        self.assertEqual(message.count("Shared."), 1)
        self.assertIn("Other.", message)

    def test_a_broken_guard_refuses(self):
        def broken(sender, change, **kwargs):
            raise RuntimeError("bug")

        self.connect(broken, "test.broken")
        with (
            self.assertLogs("evennia", "ERROR"),
            self.assertRaisesMessage(ChargenError, guards.GUARD_FAILED),
        ):
            services.set_edge(self.char1, "brawn", 0)
        self.assertEqual(self.rating(self.char1), "Mid ++")

    def test_an_answer_that_isnt_a_message_refuses(self):
        self.connect(lambda sender, change, **kw: True, "test.odd")
        with (
            self.assertLogs("evennia", "ERROR"),
            self.assertRaisesMessage(ChargenError, guards.GUARD_FAILED),
        ):
            services.set_edge(self.char1, "brawn", 0)

    def test_allowing_answers(self):
        self.connect(lambda sender, change, **kw: [], "test.empty")
        self.connect(lambda sender, change, **kw: "", "test.blank")
        services.set_edge(self.char1, "brawn", 0)
        self.assertEqual(self.rating(self.char1), "Mid")


class GuardCommandTests(GuardMixin, ChargenCommandTest):
    def test_setstat_shows_the_refusal_and_names_staff(self):
        self.make_sheet(self.char2)
        self.refuse[guards.RATING] = AXE
        self.call(CmdChargen(), "/setstat Char2/brawn=High", AXE, caller=self.char1)
        self.assertEqual(self.asked[-1].by, self.char1)
        self.assertEqual(self.rating(self.char2), "Low")


class FrozenTests(ChargenTest):
    def test_a_locked_final_sheet_is_frozen(self):
        self.make_sheet(self.char1)
        self.assertFalse(locks.frozen(self.char1))
        locks.lock(self.char1)
        self.assertTrue(locks.frozen(self.char1))
        locks.unlock(self.char1)
        self.assertFalse(locks.frozen(self.char1))

    def test_drafts_never_freeze(self):
        self.make_sheet(self.char1, finalize=False)
        locks.lock(self.char1)
        self.assertFalse(locks.frozen(self.char1))

    @override_settings(RP_CHARGEN_LOCK_SCOPES=("pips",))
    def test_any_scope_freezes(self):
        self.make_sheet(self.char1)
        locks.lock(self.char1)
        self.assertTrue(locks.frozen(self.char1))

    @override_settings(RP_CHARGEN_LOCK_SCOPES=())
    def test_no_scopes_never_freeze(self):
        self.make_sheet(self.char1)
        locks.lock(self.char1)
        self.assertFalse(locks.frozen(self.char1))

    @override_settings(RP_CHARGEN_PIP_NOUN="edge")
    def test_locked_message_names_what_is_frozen(self):
        self.assertEqual(
            locks.locked_message(),
            "Your edge and loadout are locked for the scene. Use +unlock first; the room is told.",
        )
