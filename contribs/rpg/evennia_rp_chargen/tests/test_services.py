# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Stat storage, sheet services, the build life cycle, and the subject adapter."""

from __future__ import annotations

from django.test import override_settings

from evennia_rp_chargen import locks, services
from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.stats import ATTR_CATEGORY, ATTR_KEY, StatHandler
from evennia_rp_chargen.subject import ChargenSubject, subject_adapter
from evennia_rp_rules.checks import Check, CheckError, resolve_check

from .base import POINT_BUY, ChargenTest


class StatHandlerTests(ChargenTest):
    def test_stores_rung_keys_and_pips_only(self):
        handler = StatHandler(self.char1)
        handler.set("brawn", self.ruleset.parse_rating("Mid++-"))
        raw = self.char1.attributes.get(ATTR_KEY, category=ATTR_CATEGORY)
        self.assertEqual(raw["_v"], 1)
        self.assertEqual(dict(raw["brawn"]), {"rung": "mid", "edge": 2, "weak": 1})
        self.assertEqual(handler.get("brawn").display(), "Mid ++ -")

    def test_unset_and_ordering(self):
        handler = StatHandler(self.char1)
        handler.set_rung("charm", "high")
        self.assertEqual(list(handler.ratings()), ["brawn", "brains", "charm"])
        self.assertEqual([s.key for s in handler.unset()], ["brawn", "brains"])

    def test_set_rung_keeps_pips_and_set_pips_needs_a_rung(self):
        handler = StatHandler(self.char1)
        with self.assertRaises(LookupError):
            handler.set_pips("brawn", edge=1)
        handler.set_rung("brawn", "Mid")
        handler.set_pips("brawn", edge=2, weakness=1)
        self.assertEqual(handler.set_rung("brawn", "High").display(), "High ++ -")
        with self.assertRaises(ValueError):
            handler.set_rung("brawn", "Epic")
        with self.assertRaises(ValueError):
            handler.set_pips("brawn", edge=4)

    def test_entries_invalidated_by_a_ruleset_change(self):
        self.char1.attributes.add(
            ATTR_KEY,
            {"_v": 1, "brawn": {"rung": "legendary"}, "luck": {"rung": "mid"}},
            category=ATTR_CATEGORY,
        )
        handler = StatHandler(self.char1)
        self.assertIsNone(handler.get("brawn"))
        problems = handler.problems()
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("luck" in p for p in problems))

    def test_clear_and_edge_total(self):
        handler = StatHandler(self.char1)
        handler.set("brawn", self.ruleset.parse_rating("Mid++"))
        handler.set("charm", self.ruleset.parse_rating("Low+"))
        self.assertEqual(handler.edge_total(), 3)
        handler.clear("brawn")
        self.assertIsNone(handler.get("brawn"))


@override_settings(RP_CHARGEN_ALLOCATION=POINT_BUY)
class DraftTests(ChargenTest):
    def test_set_stat_within_budget(self):
        rating, report = services.set_stat(self.char1, "braw", "high")
        self.assertEqual(rating.display(), "High")
        self.assertEqual(report.spent, 3)
        self.assertEqual(services.get_build(self.char1).allocation_spent, 3)

    def test_overspending_is_refused_and_nothing_changes(self):
        services.set_stat(self.char1, "brawn", "High")
        with self.assertRaisesMessage(ChargenError, "costs 6 build points"):
            services.set_stat(self.char1, "brains", "High")
        self.assertIsNone(StatHandler(self.char1).get("brains"))

    def test_pips_are_refused_in_stats(self):
        with self.assertRaisesMessage(ChargenError, "+pips"):
            services.set_stat(self.char1, "brawn", "Mid+")

    def test_unknown_stat_and_rung(self):
        with self.assertRaisesMessage(ChargenError, "Unknown stat"):
            services.set_stat(self.char1, "luck", "Mid")
        with self.assertRaisesMessage(ChargenError, "Unknown"):
            services.set_stat(self.char1, "brawn", "Epic")

    def test_finalize_lists_what_is_left(self):
        services.set_stat(self.char1, "brawn", "High")
        with self.assertRaisesMessage(ChargenError, "Set Brains, Charm."):
            services.finalize(self.char1)
        services.set_stat(self.char1, "brains", "Mid")
        services.set_stat(self.char1, "charm", "Low")
        build = services.finalize(self.char1)
        self.assertEqual(build.status, CharacterBuild.Status.FINALIZED)
        self.assertIsNotNone(build.finalized_at)
        self.assertEqual(build.allocation_spent, 4)

    def test_finalized_rungs_are_staff_only(self):
        self.make_sheet(self.char1, brawn="High")
        with self.assertRaisesMessage(ChargenError, "final"):
            services.set_stat(self.char1, "brawn", "Mid")
        with self.assertRaisesMessage(ChargenError, "already finalized"):
            services.finalize(self.char1)

    def test_clear_stat(self):
        services.set_stat(self.char1, "brawn", "High")
        report = services.clear_stat(self.char1, "brawn")
        self.assertEqual(report.spent, 0)


@override_settings(RP_CHARGEN_PIP_BUDGET=3, RP_CHARGEN_PIP_CAP=2)
class PipServiceTests(ChargenTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char1, brawn="Mid", brains="Mid", charm="Mid")

    def test_edge_within_policy(self):
        self.assertEqual(services.set_edge(self.char1, "brawn", 2).display(), "Mid ++")
        with self.assertRaisesMessage(ChargenError, "at most 2 pips"):
            services.set_edge(self.char1, "brains", 3)
        with self.assertRaisesMessage(ChargenError, "4 pips in all"):
            services.set_edge(self.char1, "brains", 2)
        services.set_edge(self.char1, "brains", 1)

    def test_weakness_is_free_and_capped_by_the_scale(self):
        services.set_edge(self.char1, "brawn", 2)
        self.assertEqual(services.set_weakness(self.char1, "brawn", 3).display(), "Mid ++ ---")
        with self.assertRaisesMessage(ChargenError, "at most 3 weakness"):
            services.set_weakness(self.char1, "charm", 4)

    def test_negative_counts_refused(self):
        with self.assertRaisesMessage(ChargenError, "whole number"):
            services.set_edge(self.char1, "brawn", -1)

    def test_clear_edge(self):
        services.set_edge(self.char1, "brawn", 2)
        services.set_edge(self.char1, "charm", 1)
        services.set_weakness(self.char1, "charm", 1)
        self.assertEqual(len(services.clear_edge(self.char1)), 2)
        self.assertEqual(StatHandler(self.char1).get("charm").display(), "Mid -")

    def test_locked_build_refuses_pip_changes(self):
        locks.lock(self.char1)
        with self.assertRaisesMessage(ChargenError, "locked"):
            services.set_edge(self.char1, "brawn", 1)
        locks.unlock(self.char1)
        services.set_edge(self.char1, "brawn", 1)

    @override_settings(RP_CHARGEN_LOCK_SCOPES=("loadout",))
    def test_scopes_decide_what_locks(self):
        locks.lock(self.char1)
        services.set_edge(self.char1, "brawn", 1)

    def test_a_tightened_policy_still_lets_players_move_towards_it(self):
        services.set_edge(self.char1, "brawn", 2)
        services.set_edge(self.char1, "brains", 1)
        with override_settings(RP_CHARGEN_PIP_BUDGET=1):
            services.set_edge(self.char1, "brawn", 0)  # still over budget, but less so
            with self.assertRaisesMessage(ChargenError, "in all"):
                services.set_edge(self.char1, "charm", 1)

    def test_pips_need_a_sheet_and_a_rung(self):
        with self.assertRaisesMessage(ChargenError, "sheet"):
            services.set_edge(self.char2, "brawn", 1)
        services.ensure_build(self.char2)
        with self.assertRaisesMessage(ChargenError, "first"):
            services.set_edge(self.char2, "brawn", 1)


class LifecycleTests(ChargenTest):
    def test_approve_and_reopen(self):
        build = self.make_sheet(self.char2)
        build = services.approve(self.char2, by=self.char1, note="Looks good")
        self.assertEqual(build.status, CharacterBuild.Status.APPROVED)
        self.assertEqual(build.reviewed_by, self.account)
        self.assertEqual(build.review_note, "Looks good")
        locks.lock(self.char2)
        build = services.reopen(self.char2, by=self.account)
        self.assertTrue(build.is_draft)
        self.assertFalse(locks.is_locked(self.char2))
        with self.assertRaisesMessage(ChargenError, "already a draft"):
            services.reopen(self.char2)
        with self.assertRaisesMessage(ChargenError, "awaiting approval"):
            services.approve(self.char2)

    def test_staff_set_stat_bypasses_policy_with_warnings(self):
        with override_settings(RP_CHARGEN_ALLOCATION=POINT_BUY, RP_CHARGEN_PIP_BUDGET=1):
            self.make_sheet(self.char2, brawn="High")
            rating, warnings = services.staff_set_stat(self.char2, "brains", "High++")
        self.assertEqual(rating.display(), "High ++")
        self.assertEqual(len(warnings), 2)
        self.assertEqual(StatHandler(self.char2).get("brains").display(), "High ++")

    def test_playable_depends_on_approval_setting(self):
        build = self.make_sheet(self.char2)
        self.assertTrue(build.is_playable)
        with override_settings(RP_CHARGEN_REQUIRE_APPROVAL=True):
            self.assertFalse(build.is_playable)
            services.approve(self.char2)
            build.refresh_from_db()
            self.assertTrue(build.is_playable)


class SubjectTests(ChargenTest):
    def check(self, actor, roll=0):
        check = Check("test", actor, "brawn", difficulty="Mid")
        return resolve_check(check, roller=self.scripted(roll))

    def test_adapter_only_for_characters_with_sheets(self):
        self.assertIsNone(subject_adapter(self.char1))
        self.assertIsNone(subject_adapter({"brawn": "Mid"}))
        self.make_sheet(self.char1)
        self.assertIsInstance(subject_adapter(self.char1), ChargenSubject)

    @override_settings(RP_RULES_SUBJECT_ADAPTER="evennia_rp_chargen.subject.subject_adapter")
    def test_checks_read_a_finalized_sheet(self):
        self.make_sheet(self.char1, brawn="High+")
        result = self.check(self.char1)
        self.assertEqual(result.actor_rating.display(), "High +")
        self.assertEqual(result.outcome.key, "great")

    @override_settings(RP_RULES_SUBJECT_ADAPTER="evennia_rp_chargen.subject.subject_adapter")
    def test_draft_and_unapproved_sheets_explain_themselves(self):
        self.make_sheet(self.char1, finalize=False)
        with self.assertRaisesMessage(CheckError, "still a draft"):
            self.check(self.char1)
        services.finalize(self.char1)
        with (
            override_settings(RP_CHARGEN_REQUIRE_APPROVAL=True),
            self.assertRaisesMessage(CheckError, "awaiting staff approval"),
        ):
            self.check(self.char1)

    @override_settings(RP_RULES_SUBJECT_ADAPTER="evennia_rp_chargen.subject.subject_adapter")
    def test_no_sheet_means_no_stats(self):
        with self.assertRaisesMessage(CheckError, "has no stats"):
            self.check(self.char2)
