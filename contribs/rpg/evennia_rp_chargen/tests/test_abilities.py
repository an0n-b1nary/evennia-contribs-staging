# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The ability catalog: seeding, vocabulary, buying, the loadout, flaws, staff tools, checks."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings

from evennia_rp_chargen import abilities, locks, services
from evennia_rp_chargen.catalog import (
    definition_problems,
    find_ability,
    modifiers_for,
    seed_catalog,
    split_ability_text,
)
from evennia_rp_chargen.models import (
    AbilityDefinition,
    AbilityTransaction,
    TagDefinition,
)
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.vocabulary import DBVocabulary, ensure_tag
from evennia_rp_rules.checks import Check, resolve_check

from .base import ChargenTest
from .catalog_fixture import CATALOG, CATALOG_SETTINGS, FakeLedger

LEDGER = f"{FakeLedger.__module__}.FakeLedger"
ADAPTER = "evennia_rp_chargen.subject.subject_adapter"


@override_settings(**CATALOG_SETTINGS)
class CatalogTest(ChargenTest):
    def setUp(self):
        super().setUp()
        seed_catalog()
        FakeLedger.reset()

    def copies(self, character):
        return {c.display_name: c for c in abilities.owned(character)}


class SeedTests(CatalogTest):
    def test_seed_creates_tags_and_abilities_once(self):
        self.assertEqual(AbilityDefinition.objects.count(), len(CATALOG))
        self.assertEqual(TagDefinition.objects.count(), 3)
        counts = seed_catalog()
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["unchanged"], len(CATALOG))

    def test_management_command(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("rp_chargen_seed", stdout=out)
        self.assertIn(f"Abilities: 0 created, 0 updated, {len(CATALOG)} unchanged.", out.getvalue())
        call_command("rp_chargen_seed", "--update", stdout=out)
        self.assertIn(f"{len(CATALOG)} updated", out.getvalue())

    def test_update_overwrites(self):
        AbilityDefinition.objects.filter(key="lucky").update(budget_cost=99)
        counts = seed_catalog(update=True)
        self.assertEqual(counts["updated"], len(CATALOG))
        self.assertEqual(AbilityDefinition.objects.get(key="lucky").budget_cost, 5)

    def test_a_bad_entry_writes_nothing(self):
        entries = [
            {"key": "fine", "name": "Fine", "effects": []},
            {"key": "broken", "name": "Broken", "effects": [{"kind": "nope"}]},
        ]
        with self.assertRaisesMessage(ValueError, "broken"):
            seed_catalog(entries=entries)
        self.assertFalse(AbilityDefinition.all_objects.filter(key="fine").exists())
        with self.assertRaisesMessage(ValueError, "unknown fields"):
            seed_catalog(entries=[{"key": "x", "name": "X", "colour": "red"}])

    def test_definition_problems(self):
        def problems(**fields):
            return " | ".join(definition_problems(AbilityDefinition(key="x", name="X", **fields)))

        self.assertIn(
            "set tag_kind", problems(effects=[{"kind": "tag_bonus", "tags": ["@tag"], "score": 1}])
        )
        self.assertIn("aren't bought with XP", problems(is_flaw=True, acquisition="xp"))
        self.assertIn(
            "unknown tag 'juggling'",
            problems(effects=[{"kind": "tag_bonus", "tags": ["juggling"], "score": 1}]),
        )
        self.assertIn("no tags of kind 'colour'", problems(tag_kind="colour"))
        self.assertIn("unknown effect kind", problems(effects=[{"kind": "nope"}]))
        self.assertEqual(problems(tag_kind="domain", effects=CATALOG[0]["effects"]), "")
        with self.assertRaises(ValidationError):
            AbilityDefinition(key="x", name="X", is_flaw=True, acquisition="xp").clean()

    def test_lookup_helpers(self):
        self.assertEqual(find_ability("domain exp").key, "domain-expertise")
        with self.assertRaises(LookupError):
            find_ability("domain")
        self.assertEqual(
            split_ability_text("Domain Expertise: Riddles"), ("Domain Expertise", "Riddles")
        )
        self.assertEqual(split_ability_text("lucky"), ("lucky", None))
        self.assertEqual(split_ability_text("expertise", "riddles"), ("expertise", "riddles"))


class VocabularyTests(CatalogTest):
    def test_ruleset_tags_overlaid_by_rows(self):
        TagDefinition.all_objects.all().delete()
        vocabulary = DBVocabulary()
        self.assertEqual([t.key for t in vocabulary.tags("domain")], ["climbing", "riddles"])
        TagDefinition.objects.create(key="juggling", name="Juggling")
        TagDefinition.objects.create(key="riddles", name="Puzzles", aliases=["enigmas"])
        self.assertEqual(vocabulary.find("enig").name, "Puzzles")
        self.assertEqual(vocabulary.get("juggling").name, "Juggling")
        TagDefinition.objects.get(key="juggling").archive()
        self.assertIsNone(vocabulary.get("juggling"))
        self.assertEqual(vocabulary.find("fire", kind="element").kind, "element")

    def test_ensure_tag_creates_from_the_ruleset(self):
        TagDefinition.all_objects.all().delete()
        row = ensure_tag(self.ruleset.tags["climbing"])
        self.assertEqual((row.key, row.name, row.kind), ("climbing", "Climbing", "domain"))
        self.assertEqual(ensure_tag(self.ruleset.tags["climbing"]).pk, row.pk)

    @override_settings(RP_RULES_VOCABULARY="evennia_rp_chargen.vocabulary.DBVocabulary")
    def test_usable_as_the_kernel_vocabulary(self):
        from evennia_rp_rules.vocabulary import get_vocabulary

        self.assertIsInstance(get_vocabulary(), DBVocabulary)


class BuyingTests(CatalogTest):
    def test_acquire_pays_from_the_allowance_and_equips(self):
        copy, payment = abilities.acquire(self.char1, "domain expertise", "rid")
        self.assertEqual(copy.display_name, "Domain Expertise: Riddles")
        self.assertTrue(copy.equipped)
        self.assertEqual((payment.allowance, payment.xp), (Decimal(3), Decimal(0)))
        build = services.get_build(self.char1)
        self.assertEqual(build.allowance_left, Decimal(2))
        tx = AbilityTransaction.objects.get(kind="acquire")
        self.assertEqual((tx.tag_key, tx.allowance_amount, tx.level_to), ("riddles", 3, 1))

    def test_templates_need_a_tag_once_per_tag(self):
        with self.assertRaisesMessage(ChargenError, "Which domain?"):
            abilities.acquire(self.char1, "domain expertise")
        abilities.acquire(self.char1, "domain expertise", "riddles")
        with self.assertRaisesMessage(ChargenError, "already have"):
            abilities.acquire(self.char1, "domain expertise", "riddles")
        with self.assertRaisesMessage(ChargenError, "Unknown domain"):
            abilities.acquire(self.char1, "domain expertise", "fire")

    def test_what_cannot_be_bought(self):
        with self.assertRaisesMessage(ChargenError, "granted by staff"):
            abilities.acquire(self.char1, "lucky")
        with self.assertRaisesMessage(ChargenError, "is a flaw"):
            abilities.acquire(self.char1, "domain ineptitude", "riddles")

    def test_without_a_ledger_the_allowance_is_the_limit(self):
        abilities.acquire(self.char1, "domain expertise", "riddles")
        with self.assertRaisesMessage(
            ChargenError, "costs 3, and you have 2 starting allowance left"
        ):
            abilities.acquire(self.char1, "domain expertise", "climbing")
        self.assertEqual(len(abilities.owned(self.char1)), 1)
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(2))
        self.assertEqual(AbilityTransaction.objects.count(), 1)

    @override_settings(RP_CHARGEN_XP_LEDGER=LEDGER)
    def test_allowance_first_then_xp(self):
        FakeLedger.reset(**{str(self.char1.id): 10})
        abilities.acquire(self.char1, "domain expertise", "riddles")
        _, payment = abilities.acquire(self.char1, "domain expertise", "climbing")
        self.assertEqual((payment.allowance, payment.xp), (Decimal(2), Decimal(1)))
        self.assertEqual(FakeLedger.balances[self.char1.id], Decimal(9))
        tx = AbilityTransaction.objects.filter(kind="acquire").first()
        self.assertTrue(tx.ledger_ref.startswith("rp_chargen.tx."))
        self.assertEqual(abilities.balance(self.char1), (Decimal(0), Decimal(9)))

    @override_settings(RP_CHARGEN_XP_LEDGER=LEDGER)
    def test_short_on_xp_changes_nothing(self):
        services.ensure_build(self.char1)
        abilities.set_allowance(self.char1, Decimal(1))
        with self.assertRaisesMessage(ChargenError, "aren't enough"):
            abilities.acquire(self.char1, "domain expertise", "riddles")
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(1))
        self.assertFalse(AbilityTransaction.objects.filter(kind="acquire").exists())

    def test_upgrades_cost_more_each_level(self):
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        copy, payment = abilities.upgrade(self.char1, "domain expertise")
        self.assertEqual((copy.level, payment.total), (2, Decimal(2)))
        copy, payment = abilities.upgrade(self.char1, "domain expertise", "riddles")
        self.assertEqual((copy.level, payment.total), (3, Decimal(4)))
        with self.assertRaisesMessage(ChargenError, "highest level (3)"):
            abilities.upgrade(self.char1, "domain expertise")
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(11))

    def test_an_unnamed_tag_is_ambiguous_with_two_copies(self):
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.acquire(self.char1, "domain expertise", "climbing")
        with self.assertRaisesMessage(
            ChargenError, "Which Domain Expertise? You have: Climbing, Riddles."
        ):
            abilities.upgrade(self.char1, "domain expertise")


class LoadoutTests(CatalogTest):
    def setUp(self):
        super().setUp()
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.acquire(self.char1, "domain expertise", "climbing")

    def test_budget(self):
        self.assertEqual(abilities.loadout_used(self.char1), 20)
        copy = abilities.grant(self.char1, "lucky")
        self.assertFalse(copy.equipped)
        with self.assertRaisesMessage(ChargenError, "needs 5 points; you have 0 of 20 free"):
            abilities.equip(self.char1, "lucky")
        abilities.unequip(self.char1, "domain expertise", "climbing")
        abilities.equip(self.char1, "lucky")
        self.assertEqual(abilities.loadout_used(self.char1), 15)
        with self.assertRaisesMessage(ChargenError, "already equipped"):
            abilities.equip(self.char1, "lucky")

    def test_locks_freeze_the_loadout_but_not_drafts(self):
        abilities.unequip(self.char1, "domain expertise", "climbing")  # draft: never locked
        self.make_sheet(self.char1, finalize=False)
        services.finalize(self.char1)
        locks.lock(self.char1)
        with self.assertRaisesMessage(ChargenError, "locked"):
            abilities.equip(self.char1, "domain expertise", "climbing")
        locks.unlock(self.char1)
        abilities.equip(self.char1, "domain expertise", "climbing")

    def test_acquiring_while_locked_leaves_it_unequipped(self):
        self.make_sheet(self.char2)
        abilities.set_allowance(self.char2, Decimal(5))
        locks.lock(self.char2)
        copy, _ = abilities.acquire(self.char2, "domain expertise", "riddles")
        self.assertFalse(copy.equipped)


class FlawTests(CatalogTest):
    def test_take_and_remove(self):
        copy = abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.assertTrue(copy.equipped)
        with self.assertRaisesMessage(ChargenError, "stay in effect"):
            abilities.unequip(self.char1, "domain ineptitude")
        self.assertEqual(
            abilities.remove_flaw(self.char1, "domain ineptitude"), "Domain Ineptitude: Climbing"
        )
        kinds = list(AbilityTransaction.objects.values_list("kind", flat=True))
        self.assertEqual(sorted(kinds), ["flaw_add", "flaw_remove"])
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(5))

    def test_staff_flaws(self):
        with self.assertRaisesMessage(ChargenError, "given by staff"):
            abilities.take_flaw(self.char1, "cursed")
        abilities.grant(self.char1, "cursed")
        self.assertTrue(self.copies(self.char1)["Cursed"].equipped)
        with self.assertRaisesMessage(ChargenError, "ask them"):
            abilities.remove_flaw(self.char1, "cursed")

    def test_flaws_freeze_with_the_loadout(self):
        self.make_sheet(self.char1)
        locks.lock(self.char1)
        with self.assertRaisesMessage(ChargenError, "locked"):
            abilities.take_flaw(self.char1, "domain ineptitude", "riddles")


class StaffTests(CatalogTest):
    def test_grant_and_set_level(self):
        copy = abilities.grant(self.char1, "domain expertise", "riddles", level=2, by=self.char1)
        self.assertEqual(copy.level, 2)
        copy = abilities.grant(self.char1, "domain expertise", "riddles", level=3)
        self.assertEqual(copy.level, 3)
        with self.assertRaisesMessage(ChargenError, "level 1 to 3"):
            abilities.grant(self.char1, "domain expertise", "riddles", level=4)
        tx = AbilityTransaction.objects.filter(kind="grant").last()
        self.assertEqual(tx.actor, self.account)

    def test_revoke_with_refund_counts_only_this_copy(self):
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.revoke(self.char1, "domain expertise", "riddles")  # no refund
        abilities.acquire(self.char1, "domain expertise", "riddles")
        abilities.upgrade(self.char1, "domain expertise", "riddles")
        name, refunded, kept = abilities.revoke(self.char1, "domain expertise", refund=True)
        self.assertEqual(name, "Domain Expertise: Riddles")
        self.assertEqual(refunded.allowance, Decimal(5))  # 3 + 2, not the first copy's 3
        self.assertEqual(services.get_build(self.char1).allowance_left, Decimal(17))
        self.assertEqual(kept, Decimal(0))

    @override_settings(RP_CHARGEN_XP_LEDGER=LEDGER)
    def test_xp_refunds_go_back_through_the_ledger(self):
        FakeLedger.reset(**{str(self.char1.id): 10})
        abilities.set_allowance(self.char1, Decimal(0))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        _, refunded, kept = abilities.revoke(self.char1, "domain expertise", refund=True)
        self.assertEqual((refunded.xp, kept), (Decimal(3), Decimal(0)))
        self.assertEqual(FakeLedger.balances[self.char1.id], Decimal(10))

    def test_xp_without_a_ledger_is_reported_not_lost(self):
        with override_settings(RP_CHARGEN_XP_LEDGER=LEDGER):
            FakeLedger.reset(**{str(self.char1.id): 10})
            abilities.set_allowance(self.char1, Decimal(0))
            abilities.acquire(self.char1, "domain expertise", "riddles")
        _, refunded, kept = abilities.revoke(self.char1, "domain expertise", refund=True)
        self.assertEqual((refunded.xp, kept), (Decimal(0), Decimal(3)))

    def test_allowance_default_and_override(self):
        build = services.ensure_build(self.char1)
        self.assertEqual(build.allowance_total, Decimal(5))
        build = abilities.set_allowance(self.char1, Decimal(12))
        self.assertEqual(build.allowance_total, Decimal(12))
        build = abilities.set_allowance(self.char1, None)
        self.assertEqual(build.allowance_total, Decimal(5))
        with self.assertRaisesMessage(ChargenError, "negative"):
            abilities.set_allowance(self.char1, Decimal(-1))


@override_settings(RP_RULES_SUBJECT_ADAPTER=ADAPTER)
class ChecksTests(CatalogTest):
    def check(self, actor, tags=(), opponent=None, stat="brains"):
        kwargs = {"opponent": opponent} if opponent else {"difficulty": "Mid"}
        check = Check("test", actor, stat, tags=tags, **kwargs)
        return resolve_check(check, roller=self.scripted(0))

    def test_equipped_expertise_reaches_checks(self):
        self.make_sheet(self.char1, brains="Mid")
        abilities.set_allowance(self.char1, Decimal(20))
        abilities.acquire(self.char1, "domain expertise", "riddles")
        result = self.check(self.char1, tags={"riddles"})
        self.assertEqual(
            [e.describe() for e in result.entries_for("actor")], ["Domain Expertise: Riddles +2"]
        )
        abilities.upgrade(self.char1, "domain expertise")
        self.assertEqual(self.check(self.char1, tags={"riddles"}).bonuses["actor"], 3)
        self.assertEqual(self.check(self.char1, tags={"climbing"}).bonuses["actor"], 0)
        # The checks locked the build; the loadout stays frozen until unlocked.
        with self.assertRaisesMessage(ChargenError, "locked"):
            abilities.unequip(self.char1, "domain expertise")
        locks.unlock(self.char1)
        abilities.unequip(self.char1, "domain expertise")
        self.assertEqual(self.check(self.char1, tags={"riddles"}).bonuses["actor"], 0)

    def test_flaws_reach_checks(self):
        self.make_sheet(self.char1, brains="Mid")
        self.make_sheet(self.char2, brains="Mid")
        abilities.take_flaw(self.char1, "domain ineptitude", "riddles")
        self.assertEqual(self.check(self.char1, tags={"riddles"}).bonuses["actor"], -2)
        abilities.take_flaw(self.char2, "domain vulnerability", "riddles")
        result = self.check(self.char1, tags={"riddles"}, opponent=self.char2)
        self.assertEqual(result.bonuses, {"actor": -2, "target": -2})
        ledger = {e.key: (e.owner, e.source) for e in result.ledger}
        self.assertEqual(ledger["domain-vulnerability:riddles"], ("target", "flaw"))

    def test_drafts_offer_no_modifiers(self):
        self.make_sheet(self.char1, finalize=False)
        abilities.take_flaw(self.char1, "domain ineptitude", "riddles")
        from evennia_rp_chargen.subject import ChargenSubject

        self.assertEqual(ChargenSubject(self.char1).get_modifiers(None), [])
        self.assertEqual(len(modifiers_for(self.char1)), 1)
