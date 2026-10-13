# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Checks: real damage/turns, participation, raid isolation and transactions."""

from copy import deepcopy
from fractions import Fraction as F
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_combat import engine, partners
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import CombatError

from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.subjects import DictStatSource
from evennia_rp_rules.testing import RulesetTestMixin

from . import boss, boss_services, rules, services, subjects, synergy
from .boss_commands import CmdBossCheck
from .tests import REGISTRY, build, declare, teams


def stat_block_adapter(subject):
    return DictStatSource(subject.attributes.get("contest_test_stats"))


def check(state, party, kind="tank", **kwargs):
    return boss.issue(state, 1, [party], kind, **kwargs)[0]


def resolve(state, ident, **kwargs):
    preview = boss.preview(state, ident, verdict=kwargs.get("verdict"))
    return boss.resolve(
        state, ident, preview["token"], acknowledgment="Responses reviewed", **kwargs
    )


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestBossRules(SimpleTestCase):
    def setUp(self):
        self.state, self.own, self.party = teams(boss=3)

    def test_issue_starts_assessment_without_action_or_resource_awards(self):
        before = deepcopy(self.state["participants"])
        ident = check(self.state, self.party)
        self.assertEqual(self.state["participants"], before)
        self.assertTrue(self.state["started"])
        self.assertEqual(synergy.pool(self.state, self.own), 0)
        self.assertEqual(boss.get(self.state, ident)["cohort"], ["4", "5", "6"])

    def test_raid_batch_is_independent_and_bad_target_cannot_partially_issue(self):
        rules.leave(self.state, 6)
        third = rules.create(self.state, 6, "Third")
        before = deepcopy(self.state)
        with self.assertRaises(CombatError):
            boss.issue(self.state, 1, [self.party, self.own], "dps")
        self.assertEqual(self.state, before)
        ids = boss.issue(self.state, 1, [self.party, third], "dps")
        boss.cancel(self.state, ids[0], 4)
        self.assertEqual(boss.get(self.state, ids[1])["status"], "pending")
        with self.assertRaisesRegex(CombatError, "already challenged"):
            check(self.state, self.party)

    def test_one_pending_check_per_party_across_bosses(self):
        check(self.state, self.party)
        self.state["participants"]["2"]["allowance"] = 2
        with self.assertRaisesRegex(CombatError, "unresolved"):
            boss.issue(self.state, 2, [self.party], "support")

    @override_settings(RP_PARTY_STAGGER_POINTS="30/1")
    def test_raid_successes_do_not_stack_or_refresh_stagger_and_failures_are_local(self):
        rules.leave(self.state, 6)
        third = rules.create(self.state, 6, "Third")
        ids = boss.issue(self.state, 1, [self.party, third], "support", options={"value": "0"})
        resolve(self.state, ids[0])
        skip = deepcopy(self.state["participants"]["1"]["turn_skip"])
        resolve(self.state, ids[1])
        self.assertEqual(self.state["participants"]["1"]["turns"], 1)
        self.assertEqual(self.state["participants"]["1"]["turn_skip"], skip)
        self.assertEqual(engine.value(self.state["participants"]["1"], "staggered"), 30)
        # A different boss can issue after those instances end. Failure is
        # applied only to its challenged Party, never all allies on the side.
        self.state["participants"]["2"]["allowance"] = 2
        self.state["participants"]["2"]["actions_left"] = 2
        other = boss.issue(self.state, 2, [third], "dps")[0]
        resolve(self.state, other)
        self.assertEqual(self.state["participants"]["6"]["hp"], 88)
        self.assertEqual(self.state["participants"]["4"]["hp"], 100)

    def test_cancel_does_not_reset_issuance_by_recreating_party(self):
        ident = check(self.state, self.party)
        boss.cancel(self.state, ident, 4)
        rules.leave(self.state, 4)
        replacement = rules.create(self.state, 4, "Replacement")
        with self.assertRaisesRegex(CombatError, "already challenged"):
            check(self.state, replacement)

    def test_membership_locks_allow_formation_and_individual_departure_without_replacement(self):
        ident = check(self.state, self.party)
        for operation in (
            lambda: rules.join(self.state, 2, self.party),
            lambda: rules.leave(self.state, 4),
            lambda: rules.dissolve(self.state, 4, self.party),
        ):
            with self.assertRaises(CombatError):
                operation()
        rules.formation(self.state, 4, "front")
        boss.cancel(self.state, ident, 4, individual=True)
        rules.leave(self.state, 4)
        self.assertEqual(boss.eligible(self.state, boss.get(self.state, ident)), ["5", "6"])
        with self.assertRaises(CombatError):
            rules.join(self.state, 4, self.party)
        self.assertEqual(boss.get(self.state, ident)["status"], "pending")

    def test_all_individual_withdrawals_close_without_rewards_or_damage(self):
        ident = check(self.state, self.party)
        before = deepcopy(self.state["participants"])
        for member in (4, 5, 6):
            boss.cancel(self.state, ident, member, individual=True)
        self.assertEqual(boss.get(self.state, ident)["status"], "canceled")
        self.assertEqual(self.state["participants"], before)

    def test_incapacitation_recovery_scales_only_original_cohort(self):
        self.state["participants"]["6"]["hp"] = 0
        ident = check(self.state, self.party)
        row = boss.get(self.state, ident)
        self.assertEqual(len(row["cohort"]), 2)
        self.state["participants"]["6"]["hp"] = 100
        self.state["participants"]["5"]["recovering"] = True
        self.assertEqual(boss.eligible(self.state, row), ["4"])
        self.assertEqual(boss.required(row, 1), 35)
        self.state["participants"]["5"]["recovering"] = False
        self.assertEqual(boss.eligible(self.state, row), ["4", "5"])
        boss.cancel(self.state, ident, 6, individual=True)
        rules.leave(self.state, 6)
        self.assertEqual(boss.eligible(self.state, row), ["4", "5"])

    def test_tank_all_front_resist_proportional_backlash_and_real_damage_resources(self):
        for member in (4, 5, 6):
            rules.formation(self.state, member, "front")
        ident = check(self.state, self.party)
        result = resolve(self.state, ident, draws={"4": 1, "5": 100, "6": 1})
        self.assertTrue(result["passed"])
        self.assertEqual(result["backlash"], 53)
        damage = sum(value["damage"] for value in result["damage"].values())
        self.assertEqual(synergy.pool(self.state, self.party), F(damage, 4))
        self.assertEqual(synergy.pool(self.state, self.own), F(53, 4))
        self.assertEqual(self.state["participants"]["1"]["turns"], 1)
        self.assertGreater(self.state["participants"]["4"]["pressure"], 0)
        self.assertGreater(self.state["participants"]["4"]["transcendence"], 0)
        self.assertEqual(self.state["participants"]["4"]["clock"], 0)

    def test_tank_partial_casualty_fails_without_collapse_wave(self):
        for member in (4, 5, 6):
            rules.formation(self.state, member, "front")
        self.state["participants"]["4"]["hp"] = 1
        ident = check(self.state, self.party)
        result = resolve(self.state, ident, draws={"4": 100, "5": 100, "6": 100})
        self.assertFalse(result["passed"])
        self.assertFalse(result["collapse"])
        self.assertEqual(self.state["participants"]["5"]["hp"], 65)
        self.assertFalse(any(key.startswith("failure/") for key in result["damage"]))
        self.assertEqual(self.state["participants"]["1"]["hp"], 300)

    def test_front_collapse_does_not_shrink_test_or_damage_incapacitated_again(self):
        rules.formation(self.state, 4, "front")
        self.state["participants"]["4"]["hp"] = 20
        ident = check(self.state, self.party)
        result = resolve(self.state, ident, draws={"4": 100})
        self.assertEqual(result["threshold"], "105")
        self.assertTrue(result["collapse"])
        self.assertNotIn("failure/4", result["damage"])
        self.assertEqual(self.state["participants"]["5"]["hp"], 88)
        self.assertEqual(self.state["participants"]["4"]["hp"], 0)

    def test_empty_front_fails_and_all_unavailable_cannot_auto_pass(self):
        ident = check(self.state, self.party)
        result = resolve(self.state, ident, draws={})
        self.assertTrue(result["collapse"])
        self.assertEqual([self.state["participants"][str(i)]["hp"] for i in (4, 5, 6)], [88] * 3)
        self.state, _, self.party = teams(boss=3)
        ident = check(self.state, self.party)
        for member in (4, 5, 6):
            self.state["participants"][str(member)]["hp"] = 0
        with self.assertRaisesRegex(CombatError, "No eligible"):
            boss.preview(self.state, ident)
        boss.cancel(self.state, ident, 4)

    def test_dps_counts_burst_hits_and_overpower_not_outsiders_or_periodic_effects(self):
        ident = check(self.state, self.party, "dps")
        token = declare(self.state, 4, 1, burst=True)
        engine.reaction(self.state, 1, token, "resist")
        engine.press(self.state, 4, 100)
        engine.reaction(self.state, 1, token.replace(":1", ":2"), "resist")
        engine.press(self.state, 4, 100, stop=True)
        damage = sum(boss.get(self.state, ident)["damage"].values())
        self.assertGreater(damage, 18)
        partners.emit(
            self.state, partners.Event("hostile_damage", "4", "poison", 0, "1", damage=30)
        )
        self.assertEqual(sum(boss.get(self.state, ident)["damage"].values()), damage)
        self.state["participants"]["1"]["pose"] = False
        token = declare(self.state, 1, 5, roll=1)
        engine.reaction(self.state, 5, token, "overpower")
        self.assertGreater(sum(boss.get(self.state, ident)["damage"].values()), damage)

    def test_withdrawn_future_damage_excluded_prior_damage_kept(self):
        ident = check(self.state, self.party, "dps")
        token = declare(self.state, 4, 1)
        engine.reaction(self.state, 1, token, "resist")
        previous = deepcopy(boss.get(self.state, ident)["damage"])
        boss.cancel(self.state, ident, 4, individual=True)
        self.state["participants"]["4"]["pose"] = False
        token = declare(self.state, 4, 1)
        engine.reaction(self.state, 1, token, "resist")
        self.assertEqual(boss.get(self.state, ident)["damage"], previous)

    def test_support_final_boost_rally_and_pressure_current_not_historical(self):
        ident = check(self.state, self.party, "support", options={"value": "5"})
        self.state["participants"]["4"]["spirit"] = 0
        rules.data(self.state)["support"]["5"] = {
            "party": self.party,
            "kind": "rally",
            "points": "5",
            "source_clock": 0,
        }
        self.assertTrue(resolve(self.state, ident)["passed"])
        self.state, _, self.party = teams(boss=3)
        ident = check(self.state, self.party, "pressure")
        self.state["participants"]["1"]["spirit"] = -600
        self.state["participants"]["1"]["spirit"] = -200
        self.assertFalse(resolve(self.state, ident)["passed"])

    def test_preview_stale_pending_exchange_and_warning_override(self):
        ident = check(self.state, self.party, "dps")
        token = declare(self.state, 4, 1)
        with self.assertRaisesRegex(CombatError, "pending exchanges"):
            boss.preview(self.state, ident)
        engine.reaction(self.state, 1, token, "resist")
        view = boss.preview(self.state, ident)
        self.assertTrue(view["warnings"])
        before = deepcopy(self.state)
        with self.assertRaisesRegex(CombatError, "Acknowledge"):
            boss.resolve(self.state, ident, view["token"])
        self.assertEqual(self.state, before)
        rules.formation(self.state, 5, "front")
        with self.assertRaisesRegex(CombatError, "stale"):
            boss.resolve(self.state, ident, view["token"], acknowledgment="table ready")
        resolve(self.state, ident)

    def test_equal_partial_response_turns_warn_and_capped_defenders_still_count(self):
        for member in ("4", "5", "6"):
            self.state["participants"][member].update(allowance=3, actions_left=3)
        ident = check(self.state, self.party, "support")
        for member in ("4", "5", "6"):
            self.state["participants"][member]["actions_spent"] = 1
        warnings = boss.warnings(self.state, boss.get(self.state, ident))
        self.assertTrue(any("partway" in warning for warning in warnings))
        self.assertFalse(any("Uneven" in warning for warning in warnings))
        self.state["participants"]["4"]["turns"] = self.state["participants"]["4"]["turn_limit"]
        self.assertIn("4", boss.eligible(self.state, boss.get(self.state, ident)))

    def test_special_explicit_judgment_and_committed_consequences_need_staff(self):
        with self.assertRaisesRegex(CombatError, "bounded"):
            check(
                self.state,
                self.party,
                "special",
                options={"requirement": "x" * 321, "hint": "Look up"},
            )
        ident = check(
            self.state,
            self.party,
            "special",
            options={"requirement": "Break the seal", "hint": "The three stones"},
        )
        with self.assertRaisesRegex(CombatError, "choose pass or fail"):
            boss.preview(self.state, ident)
        self.assertTrue(resolve(self.state, ident, verdict=True)["passed"])
        before = deepcopy(self.state)
        with self.assertRaisesRegex(CombatError, "staff"):
            boss.cancel(self.state, ident, 4)
        self.assertEqual(self.state, before)

    def test_suspend_fade_cancel_defeat_and_read_upgrade_preserve_pending_data(self):
        ident = check(self.state, self.party)
        self.state["participants"]["1"]["status"] = "faded"
        boss.reconcile(self.state)
        self.assertEqual(boss.get(self.state, ident)["status"], "pending")
        self.state["paused"] = True
        boss.cancel(self.state, ident, 4, individual=True)
        upgraded = rules.upgrade(self.state["partners"]["party"])
        self.assertEqual(upgraded, self.state["partners"]["party"])
        self.state["participants"]["1"]["hp"] = 0
        boss.reconcile(self.state)
        self.assertEqual(boss.get(self.state, ident)["status"], "canceled")


@override_settings(RP_COMBAT_PARTNERS=REGISTRY, RP_COMBAT_REVEALED=True, RP_PARTY_REVEALED=True)
class TestBossCoordinator(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        source = patch("evennia_rp_combat.services.snapshot", return_value=build())
        source.start()
        self.addCleanup(source.stop)
        combat.setup(self.char1)
        combat.join(self.char1, "boss", boss=3)
        combat.join(self.char2, "heroes")
        self.party = services.change(self.char2, "create", "Heroes")

    def test_issue_resolve_idempotency_and_outsider_permission(self):
        ids = boss_services.issue(
            self.char1, [self.party], "support", options={"value": "0"}, operation_id="issue-one"
        )
        self.assertEqual(
            boss_services.issue(
                self.char1,
                [self.party],
                "support",
                options={"value": "0"},
                operation_id="issue-one",
            ),
            ids,
        )
        with self.assertRaises(CombatError):
            boss_services.preview(self.char2, ids[0])
        view = boss_services.preview(self.char1, ids[0])
        result = boss_services.resolve(
            self.char1,
            ids[0],
            view["token"],
            acknowledgment="Intentionally easy",
            operation_id="resolve-one",
        )
        state = combat.state_for(self.char1)
        self.assertEqual(
            boss_services.resolve(
                self.char1,
                ids[0],
                view["token"],
                acknowledgment="Intentionally easy",
                operation_id="resolve-one",
            ),
            result,
        )
        self.assertEqual(combat.state_for(self.char1), state)
        self.assertEqual(state["participants"][str(self.char1.pk)]["turns"], 1)

    def test_cancel_is_cleanup_during_pause_and_party_freeze(self):
        ident = boss_services.issue(self.char1, [self.party], "dps")[0]
        combat.storyteller(self.char1, "pause")
        with override_settings(RP_PARTY_FROZEN=True):
            boss_services.cancel(self.char2, ident, individual=True)
        self.assertEqual(boss.get(combat.state_for(self.char1), ident)["status"], "canceled")

    def test_older_optional_contest_does_not_block_relock_or_other_checks(self):
        installed = apps.is_installed
        with (
            patch(
                "evennia_rp_party.subjects.apps.is_installed",
                side_effect=lambda label: label == "evennia_rp_contest" or installed(label),
            ),
            patch(
                "evennia_rp_party.subjects.import_module",
                side_effect=ModuleNotFoundError("Old Contest", name="evennia_rp_contest.bound"),
            ),
        ):
            self.assertIsNone(subjects.snapshot(self.char2))
            with self.assertRaisesRegex(CombatError, "unavailable"):
                boss_services.contest_provider()
            combat.control(self.char2, "unlock")
            combat.control(self.char2, "relock")
            ident = boss_services.issue(self.char1, [self.party], "tank")[0]
            boss_services.cancel(self.char2, ident)

    def test_commands_register_and_no_dice_in_status_or_preview(self):
        self.call(CmdBossCheck(), "Heroes=tank", "Boss Checks issued: 1.c1.")
        self.call(CmdBossCheck(), "/preview 1.c1", "Check 1.c1")
        rendered = services.render(self.char1)
        self.assertIn("+bosscheck/withdraw", rendered)
        self.assertNotIn("rating_display", rendered)


@skipUnless(apps.is_installed("evennia_rp_contest"), "optional Contest provider absent")
@override_settings(
    RP_COMBAT_PARTNERS=REGISTRY,
    RP_COMBAT_REVEALED=True,
    RP_PARTY_REVEALED=True,
    RP_RULES_SUBJECT_ADAPTER="evennia_rp_party.test_boss.stat_block_adapter",
    RP_RULES_VOCABULARY=None,
    RP_RULES_MODIFIER_PROVIDERS=[],
)
class TestBoundContest(RulesetTestMixin, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        for character in (self.char1, self.char2):
            character.attributes.add(
                "contest_test_stats", {key: "Mid" for key in self.ruleset.stats}
            )
        self.source_patch = patch("evennia_rp_combat.services.snapshot", return_value=build())
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        combat.setup(self.char1)
        combat.join(self.char1, "boss", boss=3)
        combat.join(self.char2, "heroes")
        self.party = services.change(self.char2, "create", "Heroes")

    def offer(self):
        return boss_services.issue(self.char1, [self.party], "contest", approaches=("brains",))[0]

    def test_frozen_source_bound_attempt_not_room_test_and_rollback_on_journal_failure(self):
        from evennia_rp_contest.models import CheckRecord

        ident = self.offer()
        self.char2.attributes.add("contest_test_stats", {"brains": "High"})
        combat.control(self.char2, "unlock")
        combat.control(self.char2, "relock")
        before = CheckRecord.objects.count()
        with (
            patch("evennia_rp_combat.services.commit", side_effect=RuntimeError("journal failed")),
            self.assertRaises(RuntimeError),
        ):
            boss_services.roll(self.char2, ident, "brains", roller=ScriptedRoller([0]))
        self.assertEqual(CheckRecord.objects.count(), before)
        result = boss_services.roll(
            self.char2, ident, "brains", roller=ScriptedRoller([0]), operation_id="bound-roll"
        )
        record = CheckRecord.objects.get(pk=result["record"])
        self.assertEqual(record.rating_display, "Mid")
        self.assertIsNone(record.challenge)
        from evennia_rp_contest.narration import public_text

        with override_settings(RP_CONTEST_SHOW_RATINGS_TO_ROOM=True):
            self.assertNotIn("Mid", public_text(record))
            self.assertIn(record.detail["outcome"]["label"], public_text(record))
        self.assertEqual(
            boss_services.roll(
                self.char2, ident, "brains", roller=ScriptedRoller([]), operation_id="bound-roll"
            ),
            result,
        )
        with self.assertRaisesRegex(CombatError, "no rerolls"):
            boss_services.roll(self.char2, ident, "brains")
        view = boss_services.preview(self.char1, ident)
        self.assertTrue(boss_services.resolve(self.char1, ident, view["token"])["passed"])

    def test_individual_failure_only_no_double_wave_and_void_blocks_resolution(self):
        from django.utils import timezone
        from evennia_rp_contest.models import CheckRecord

        ident = self.offer()
        attempt = boss_services.roll(self.char2, ident, "brains", roller=ScriptedRoller([-1]))
        CheckRecord.objects.filter(pk=attempt["record"]).update(voided_at=timezone.now())
        with self.assertRaisesRegex(ValueError, "voided"):
            boss_services.preview(self.char1, ident)
        CheckRecord.objects.filter(pk=attempt["record"]).update(voided_at=None)
        view = boss_services.preview(self.char1, ident)
        result = boss_services.resolve(self.char1, ident, view["token"])
        self.assertFalse(result["passed"])
        self.assertEqual(combat.state_for(self.char1)["participants"][str(self.char2.pk)]["hp"], 88)

    def test_alternative_approved_before_roll_only(self):
        ident = self.offer()
        with self.assertRaisesRegex(ValueError, "declared approaches"):
            boss_services.roll(self.char2, ident, "brawn")
        boss_services.allow(self.char1, ident, self.char2, "brawn")
        boss_services.roll(self.char2, ident, "brawn", roller=ScriptedRoller([0]))
        with self.assertRaisesRegex(CombatError, "before rolling"):
            boss_services.allow(self.char1, ident, self.char2, "charm")

    def test_default_middle_alternative_uses_its_own_stat_scale(self):
        from evennia_rp_rules.ruleset import reset_ruleset_cache

        spec = deepcopy(self.ruleset_spec)
        spec["default_scale"] = "tier"
        spec["scales"]["other"] = deepcopy(spec["scales"]["tier"])
        for rung, label in zip(
            spec["scales"]["other"]["rungs"], ("Bottom", "Center", "Top"), strict=True
        ):
            rung.update(key=label.lower(), label=label)
        next(stat for stat in spec["stats"] if stat["key"] == "charm")["scale"] = "other"
        with override_settings(RP_RULES_RULESET=spec):
            reset_ruleset_cache()
            self.char2.attributes.add(
                "contest_test_stats", {"brawn": "Mid", "brains": "Mid", "charm": "Center"}
            )
            combat.control(self.char2, "unlock")
            combat.control(self.char2, "relock")
            ident = self.offer()
            boss_services.allow(self.char1, ident, self.char2, "charm")
            check = boss.get(combat.state_for(self.char1), ident)
            self.assertEqual(check["allowed"][str(self.char2.pk)]["charm"], "Center")
            attempt = boss_services.roll(self.char2, ident, "charm", roller=ScriptedRoller([0]))
            self.assertTrue(attempt["success"])

    def test_guest_cannot_commit_shared_check_or_bound_audit_but_can_opt_out(self):
        from evennia_rp_contest import bound
        from evennia_rp_contest.models import CheckRecord

        ident = self.offer()
        source = boss.get(combat.state_for(self.char1), ident)["contest_sources"][
            str(self.char2.pk)
        ]
        self.char2.tags.add("character", category="guest")
        before = CheckRecord.objects.count()
        self.assertIsNone(bound.snapshot(self.char2))
        with self.assertRaisesRegex(CombatError, "Guests"):
            boss_services.roll(self.char2, ident, "brains", roller=ScriptedRoller([0]))
        with self.assertRaisesRegex(ValueError, "Guests"):
            bound.perform(
                self.char2,
                source,
                {"brains": "Mid"},
                "brains",
                binding={},
                roller=ScriptedRoller([0]),
            )
        self.assertEqual(CheckRecord.objects.count(), before)
        boss_services.cancel(self.char2, ident, individual=True)
        self.assertEqual(boss.get(combat.state_for(self.char1), ident)["status"], "canceled")
