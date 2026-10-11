# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Arithmetic boundaries, interleaved queues and real Evennia persistence."""

import json
import random
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction as F
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_rp_rules.testing import RulesetTestMixin

from . import arithmetic as math
from . import engine, policies, services
from .commands import CmdCombat, CmdCombatStory, CmdTactics
from .data import TIERS, ActionView, Build, CombatError, Move, ReactionView
from .modifiers import CombatEffect

ROLES = ("attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility")


def build(**values):
    return Build(tuple((key, str(values.get(key, 0))) for key in ROLES))


def duel(*, boss=1, attacker=None, defender=None):
    state = engine.new_state()
    engine.join(state, 1, "First", "one", attacker or build(), boss=boss)
    engine.join(state, 2, "Second", "two", defender or build())
    return state


def declare(state, *, ident=1, targets=(2,), move=None, roll=100, **kwargs):
    ex_id = engine.declaration(state, ident, targets, move or Move(), roll, **kwargs)
    return f"{ex_id}:1"


class TestArithmetic(SimpleTestCase):
    def test_calibration_anchors(self):
        chances = ((34, 52, 29), (42, 56, 37), (50, 60, 45), (58, 64, 38), (66, 68, 31))
        for (key, (power, accuracy)), expected, damage in zip(
            TIERS.items(), chances, (10, 14, 18, 22, 26), strict=True
        ):
            move = Move(key=key, power=power, accuracy=accuracy)
            for reaction, chance in zip(("evade", "resist", "overpower"), expected, strict=True):
                outcome = math.resolve(build(), build(), move, reaction, 100)
                self.assertEqual((outcome.chance, outcome.damage), (chance, damage))

    def test_pressure_matches_independent_decimal_oracle(self):
        # Decimal implementation intentionally does not reuse Fraction helpers.
        for defensive in (-20, 0, 20):
            for pressure in range(31):
                for power, accuracy in TIERS.values():
                    expected_chance = max(
                        5,
                        min(
                            95,
                            int(
                                (
                                    Decimal(60)
                                    + Decimal(".7") * defensive
                                    - 4 * accuracy
                                    - Decimal(".5") * pressure
                                ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                            ),
                        ),
                    )
                    raw = max(
                        Decimal(4),
                        min(Decimal(45), Decimal(18) - Decimal(".35") * defensive + 4 * power),
                    )
                    fraction = max(
                        Decimal(".25"),
                        min(
                            Decimal(".85"),
                            Decimal(".30")
                            - Decimal(".005") * defensive
                            + Decimal(".01") * pressure,
                        ),
                    )
                    expected_damage = int(
                        (raw * fraction).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                    )
                    prevented = (
                        int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP)) - expected_damage
                    )
                    result = math.resolve(
                        build(),
                        build(attack_defense=defensive),
                        Move(power=power, accuracy=accuracy),
                        "resist",
                        1,
                        pressure=pressure,
                    )
                    self.assertEqual(
                        (result.chance, result.damage, result.pressure_gain),
                        (expected_chance, expected_damage, prevented),
                    )
                    failed = math.resolve(
                        build(),
                        build(attack_defense=defensive),
                        Move(power=power, accuracy=accuracy),
                        "resist",
                        100,
                        pressure=pressure,
                    )
                    self.assertEqual(failed.pressure_gain, 0)

    def test_evade_glance_domain_and_truncated_band(self):
        outcomes = [
            math.resolve(build(), build(), Move(), "evade", roll)
            for roll in (50, 51, 58, 59, 60, 61)
        ]
        self.assertEqual(
            [(o.success, o.glancing, o.domain, o.damage) for o in outcomes],
            [
                (True, False, False, 0),
                (False, True, False, 9),
                (False, True, False, 9),
                (False, True, True, 9),
                (False, True, True, 9),
                (False, False, True, 18),
            ],
        )
        high = [
            math.resolve(build(), build(agility=100), Move(), "evade", r) for r in (96, 98, 99, 100)
        ]
        self.assertEqual([o.domain for o in high], [False, False, True, True])

    def test_rps_and_no_domain_on_successful_mitigation(self):
        for bet, deltas in (
            ("reaching", (-20, 0, 20)),
            ("penetrating", (20, -20, 0)),
            ("subtle", (0, 20, -20)),
        ):
            for reaction, base, delta in zip(
                ("evade", "resist", "overpower"), (50, 60, 45), deltas, strict=True
            ):
                result = math.resolve(build(), build(), Move(), reaction, 1, rps=bet)
                self.assertEqual(result.chance, base + delta)
                self.assertFalse(result.domain)

    def test_endure_and_slip_inside_only_change_declared_parts(self):
        result = math.resolve(build(), build(), Move(), "resist", 1, endure=True)
        self.assertEqual((result.damage, result.pressure_gain), (5, 0))
        move = Move(power=2, accuracy=-2)
        ordinary = math.resolve(build(), build(), move, "overpower", 1)
        slip = math.resolve(build(), build(), move, "overpower", 1, slip_inside=True)
        self.assertEqual(slip.chance - ordinary.chance, 30)
        self.assertEqual(
            (slip.damage, slip.counter_damage), (ordinary.damage, ordinary.counter_damage)
        )

    def test_rounding_clamps_and_spirit_conservation(self):
        self.assertEqual([math.rounded(F(n, 2)) for n in (-3, -1, 1, 3)], [-2, -1, 1, 2])
        self.assertEqual(math.burst_ante(-1000), (-1000, 600))
        self.assertEqual(math.burst_ante(-900), (-1000, 500))
        for own in (-1000, 0, 1999, 2000):
            for other in (-1000, -999, 0, 2000):
                for debt in (0, 600):
                    actor, target, unpaid, requested, actual = math.burst_transfer(
                        18, F(0), own, other, debt
                    )
                    self.assertEqual(actor + target - unpaid, own + other - debt)
                    self.assertTrue(-1000 <= actor <= 2000 and -1000 <= target <= 2000)
                    self.assertLessEqual(actual, requested)

    def test_support_healing_depreciates_and_repetition_only_reduces_spirit(self):
        first = math.support_values(build(), build(), "assist", 100)
        later = math.support_values(build(), build(), "assist", 100, repeat=True, heals=1)
        self.assertEqual(first, (500, 15, True))
        self.assertEqual(later, (125, 11, True))
        self.assertEqual(math.support_values(build(), build(), "dispirit", 65), (-600, 0, True))
        self.assertEqual(math.support_values(build(), build(), "dispirit", 66), (0, 0, False))


class TestSources(RulesetTestMixin, SimpleTestCase):
    def test_combat_curve_does_not_call_rating_score(self):
        from .sources import combat_score

        class Scale:
            rungs = ("d", "c", "b", "a", "s")

            def index(self, rung):
                return self.rungs.index(rung)

        self.assertEqual(
            combat_score(SimpleNamespace(scale=Scale(), rung="b", net_pips=5)), F(23, 5)
        )
        self.assertEqual(combat_score(SimpleNamespace(scale=Scale(), rung="b", net_pips=-5)), -5)
        self.assertEqual(
            combat_score(SimpleNamespace(scale=Scale(), rung="s", net_pips=1)), F(106, 5)
        )

    def test_generic_text_source_and_custom_scale(self):
        from .sources import snapshot

        class Source:
            def get_rating(self, key):
                return "Mid+"

        with override_settings(
            RP_COMBAT_ROLES={key: "brawn" for key in ROLES},
            RP_COMBAT_SCORE_BASES=(-20, 0, 20),
            RP_COMBAT_EDGE_FACTORS=(1, ".8", ".6"),
        ):
            result = snapshot(Source())
        self.assertEqual(result.score("attack"), F(8, 5))


class TestDomainsAndTraits(SimpleTestCase):
    def test_builtin_without_expertise_keeps_signature_legal(self):
        move = Move(key="grip", kind="signature", power=2, domain="athletics")
        state = duel(attacker=Build(build().scores, moves=(move,)))
        token = declare(state, move=move, domain_effects={"athletics": "grapple"})
        engine.reaction(state, 2, token, "resist")
        self.assertNotIn("grappled", engine.participant(state, 2)["conditions"])

    def test_grapple_uses_outcome_and_surcharge_once(self):
        for roll, expected in ((1, False), (100, True)):
            state = duel(
                attacker=Build(build().scores, abilities=(("proficiency", "athletics", 1),))
            )
            token = declare(
                state, roll=roll, domain="athletics", domain_effects={"athletics": "grapple"}
            )
            engine.reaction(state, 2, token, "resist")
            self.assertEqual("grappled" in engine.participant(state, 2)["conditions"], expected)
            self.assertEqual(
                engine.participant(state, 1)["reserves"], 4
            )  # 3 - surcharge + standard gain

    def test_endure_is_a_paid_reaction_and_prevents_gain(self):
        state = duel(defender=Build(build().scores, abilities=(("proficiency", "survival", 1),)))
        token = declare(state, roll=1)
        engine.reaction(
            state, 2, token, "resist", domain="survival", domain_effects={"survival": "endure"}
        )
        row = engine.participant(state, 2)
        self.assertEqual((row["pressure"], row["reserves"], row["hp"]), (0, 2, 95))

    def test_focus_required_and_healing_depreciation_is_shared(self):
        move = Move(element="sample-style")
        with override_settings(RP_COMBAT_ELEMENT_TRAITS={"sample-style": ["drain"]}):
            for focused in (False, True):
                state = duel(
                    attacker=Build(
                        build().scores,
                        abilities=(("combat-focus", "sample-style", 1),) if focused else (),
                    )
                )
                actor = engine.participant(state, 1)
                actor["hp"] = 50
                token = declare(state, move=move)
                engine.reaction(state, 2, token, "resist")
                self.assertEqual(actor["hp"], 54 if focused else 50)
                self.assertEqual(actor["heals"], 1 if focused else 0)

    def test_ward_treat_misdirect_and_analysis_keep_choices(self):
        state = duel(
            defender=Build(
                build().scores,
                abilities=(("style-resistance", "sample-style", 1),),
                flaws=(("ineptitude", "athletics"),),
            )
        )
        actor, target = engine.participant(state, 1), engine.participant(state, 2)
        engine.apply_domain(state, actor, target, "ward")
        engine.apply_domain(state, actor, target, "envenom")
        self.assertFalse(target["conditions"])
        engine.apply_domain(state, actor, target, "envenom")
        engine.apply_domain(state, actor, target, "treat")
        self.assertFalse(target["conditions"])
        engine.apply_domain(state, actor, target, "analyze")
        self.assertEqual(actor["information"]["2"]["flaws"], [("ineptitude", "athletics")])
        engine.apply_domain(state, actor, target, "misdirect")
        token = declare(state)
        view = engine.reaction_view(state, 2, token)
        self.assertFalse(view.estimates)
        self.assertEqual(policies.auto_react(view)[0], "resist")
        engine.reaction(state, 2, token, "evade")
        self.assertNotIn("misdirected", target["conditions"])

    def test_strain_reservation_prevents_negative_hp_and_refunds_cancel(self):
        move = Move(kind="signature", key="strain", power=2, effects=("strain",))
        state = duel(attacker=Build(build().scores, moves=(move,)))
        actor = engine.participant(state, 1)
        actor["hp"] = 6
        token = declare(state, move=move)
        self.assertEqual(actor["hp"], 1)
        engine.cancel(state, 2, token)
        self.assertEqual((actor["hp"], actor["transcendence"]), (6, 0))


class TestStateMachine(SimpleTestCase):
    def test_multiple_incoming_block_own_action_not_other_reactions(self):
        state = duel()
        engine.join(state, 3, "Third", "one", build())
        first, second = declare(state), declare(state, ident=3)
        with self.assertRaisesRegex(CombatError, "every incoming"):
            declare(state, ident=2, targets=(1,))
        engine.reaction(state, 2, first, "resist")
        self.assertEqual(engine.participant(state, 2)["pressure"], 0)  # failed roll
        engine.reaction(state, 2, second, "evade")
        self.assertFalse(engine.participant(state, 2)["incoming"])
        declare(state, ident=2, targets=(1,))

    def test_shared_roll_waits_for_all_and_cancel_closes_on_acceptance(self):
        state = duel(boss=3)
        engine.join(state, 3, "Third", "two", build())
        token = declare(state, targets=(2, 3), roll=60)
        engine.reaction(state, 2, token, "resist")
        exchange = state["exchanges"][token.split(":")[0]]
        self.assertEqual(exchange["outcomes"], [])
        with self.assertRaisesRegex(CombatError, "already accepted"):
            engine.cancel(state, 2, token)
        engine.reaction(state, 3, token, "resist")
        self.assertEqual([o["draw"] for o in exchange["outcomes"]], [60, 60])

    def test_accepted_reaction_freezes_pressure_and_consumes_stance(self):
        state = duel(boss=3)
        engine.join(state, 3, "Third", "two", build())
        engine.condition(engine.participant(state, 2), "resist_stance", 10)
        token = declare(state, targets=(2, 3), roll=60)
        engine.reaction(state, 2, token, "resist")
        row = engine.participant(state, 2)
        self.assertNotIn("resist_stance", row["conditions"])
        row["pressure"] = 30
        engine.reaction(state, 3, token, "resist")
        outcome = state["exchanges"][token.split(":")[0]]["outcomes"][0]
        self.assertEqual((outcome["chance"], outcome["damage"]), (70, 5))

    def test_wholly_canceled_burst_refunds_and_does_not_tick(self):
        state = duel()
        actor = engine.participant(state, 1)
        actor["transcendence"], actor["spirit"] = 100, -900
        token = declare(state, burst=True, empower=True)
        engine.cancel(state, 2, token)
        self.assertEqual(
            (actor["transcendence"], actor["spirit"], actor["clock"], actor["turns"]),
            (100, -900, 0, 0),
        )
        self.assertIsNone(actor["outgoing"])

    def test_partial_cancel_refunds_only_unexecuted_special_target(self):
        move = Move(kind="signature", power=2, name="Special", key="special")
        attacker = Build(build().scores, moves=(move,))
        state = duel(boss=3, attacker=attacker)
        engine.join(state, 3, "Third", "two", build())
        token = declare(state, targets=(2, 3), move=move)
        self.assertEqual(engine.participant(state, 1)["reserves"], 1)
        engine.reaction(state, 2, token, "resist")
        engine.cancel(state, 3, token)
        row = engine.participant(state, 1)
        self.assertEqual((row["reserves"], row["actions_left"], row["clock"]), (2, 2, 1))

    def test_burst_recovers_pressure_once_and_transfers_actual_loss(self):
        state = duel()
        actor = engine.participant(state, 1)
        actor["pressure"] = 30
        token = declare(state, burst=True)
        engine.reaction(state, 2, token, "resist")
        self.assertEqual(actor["clock"], 0)
        engine.press(state, 1, 100)
        engine.reaction(state, 2, token.replace(":1", ":2"), "resist")
        engine.press(state, 1, 100)
        engine.reaction(state, 2, token.replace(":1", ":3"), "resist")
        self.assertEqual(
            (actor["clock"], actor["turns"], actor["pressure"], actor["transcendence"]),
            (1, 1, 24, 8),
        )
        self.assertEqual(actor["spirit"], 318)
        self.assertEqual(engine.participant(state, 2)["spirit"], -918)

    def test_successful_resist_pressure_then_own_exchange_recovery(self):
        state = duel()
        token = declare(state, roll=1)
        engine.reaction(state, 2, token, "resist")
        defender = engine.participant(state, 2)
        self.assertEqual((defender["hp"], defender["pressure"]), (95, 13))
        token = declare(state, ident=2, targets=(1,))
        engine.reaction(state, 1, token, "evade")
        self.assertEqual(defender["pressure"], 7)

    def test_stances_stack_cost_accuracy_grant_and_expiry(self):
        move = Move(
            key="ready",
            kind="signature",
            power=1,
            accuracy=1,
            effects=("evade_stance", "resist_stance"),
        )
        self.assertEqual((move.cost, move.effective_accuracy), (3, -1))
        for roll, expected in ((1, 2), (100, 10)):
            state = duel(attacker=Build(build().scores, moves=(move,)))
            token = declare(state, move=move, roll=roll)
            engine.reaction(state, 2, token, "resist")
            actor = engine.participant(state, 1)
            self.assertEqual(
                [engine.value(actor, name) for name in move.effects], [expected, expected]
            )
            actor["pose"] = False
            token = declare(state)
            engine.reaction(state, 2, token, "resist")
            self.assertNotIn("evade_stance", actor["conditions"])
            self.assertNotIn("resist_stance", actor["conditions"])

    def test_stance_refresh_consumption_and_mixed_target_average(self):
        move = Move(key="ready", kind="signature", power=2, effects=("resist_stance",))
        state = duel(boss=3, attacker=Build(build().scores, moves=(move,)))
        engine.join(state, 3, "Third", "two", build(attack_defense=100))
        actor = engine.participant(state, 1)
        actor["reserves"] = 5
        token = declare(state, targets=(2, 3), move=move, roll=80)
        engine.reaction(state, 2, token, "resist")
        engine.reaction(state, 3, token, "resist")
        self.assertEqual(engine.value(actor, "resist_stance"), 6)
        engine.condition(actor, "resist_stance", 2)
        self.assertEqual(engine.value(actor, "resist_stance"), 6)

    def test_assessment_entry_fade_withdraw_and_reentry(self):
        state = duel()
        engine.opening(state)
        first = engine.participant(state, 1)
        first["hp"] = 50
        self.assertEqual(engine.assessment(state)["one"], "1/2")
        engine.join(state, 3, "Late", "one", build())
        self.assertEqual(engine.assessment(state)["one"], "1/2")
        late = engine.participant(state, 3)
        late["hp"] = 90
        engine.fade(state, 3)
        self.assertEqual(engine.assessment(state)["one"], "2/5")
        engine.join(state, 3, "Late", "one", build())
        self.assertEqual(engine.assessment(state)["one"], "2/5")
        engine.fade(state, 3, withdraw=True)
        self.assertEqual(engine.assessment(state)["one"], "-1/2")

    def test_fade_does_not_reset_build_resources_or_cap(self):
        state = duel()
        row = engine.participant(state, 1)
        row.update(hp=77, spirit=-500, reserves=1, turns=2, pressure=20)
        engine.reduce_cap(state, 1, 3)
        engine.fade(state, 1)
        engine.join(state, 1, "Different", "other", build(agility=99), turn_limit=20)
        self.assertEqual(
            (
                row["hp"],
                row["spirit"],
                row["reserves"],
                row["turns"],
                row["turn_limit"],
                row["pressure"],
                row["side"],
            ),
            (77, -500, 1, 2, 3, 20, "one"),
        )
        self.assertEqual(Build.from_dict(row["build"]).score("agility"), 0)

    def test_correction_requires_clear_queues_and_suspends_progress(self):
        state = duel()
        token = declare(state)
        with self.assertRaisesRegex(CombatError, "pending"):
            engine.correction(state, 1)
        engine.cancel(state, 2, token)
        engine.correction(state, 1)
        with self.assertRaisesRegex(CombatError, "Relock"):
            declare(state)
        engine.correction(state, 1, build=build(attack=20))
        declare(state)

    def test_burst_floor_debt_penalty_and_bounded_carry(self):
        state = duel()
        actor = engine.participant(state, 1)
        actor["spirit"] = -1000
        token = declare(state, burst=True, roll=1)
        self.assertEqual(engine.reaction_view(state, 2, token).accuracy, -6)
        engine.reaction(state, 2, token, "evade")
        self.assertEqual(actor["carry"], 600)
        actor["pose"] = False
        token = declare(state, burst=True, roll=1)
        self.assertEqual(engine.reaction_view(state, 2, token).accuracy, -6)


class TestPolicies(SimpleTestCase):
    def test_capability_views_have_no_hidden_information(self):
        state = duel()
        token = declare(state, bet="subtle", burst=True, roll=73)
        view = engine.reaction_view(state, 2, token)
        self.assertEqual(
            set(vars(view)),
            {
                "action",
                "power",
                "accuracy",
                "spirit",
                "build",
                "hp",
                "reserves",
                "transcendence",
                "spirit_self",
                "pressure",
                "penalties",
                "bonuses",
                "estimates",
            },
        )
        self.assertNotIn("bet", vars(view))
        self.assertNotIn("draw", vars(view))
        for appetite in ("cautious", "balanced", "bold"):
            reaction, counter = policies.auto_react(view, appetite=appetite)
            self.assertIn(reaction, ("evade", "resist", "overpower"))
            self.assertEqual(counter.kind, "standard")

    def test_pressure_recomputes_auto_reaction(self):
        low = ReactionView("attack", 0, 3, 0, build(attack_defense=20), pressure=0)
        high = ReactionView("attack", 0, 3, 0, build(attack_defense=20), pressure=30)
        self.assertNotEqual(policies.auto_react(low)[0], policies.auto_react(high)[0])

    def test_random_rps_frequencies_and_guesses_are_uninformed(self):
        class Draws:
            def __init__(self, n):
                self.n = n

            def choice(self, items):
                return items[0]

            def choices(self, items, **kwargs):
                return [items[0]]

            def randrange(self, limit):
                return self.n

        view = ActionView(build(), ((2, 100),), 3)
        for appetite, expected in (("cautious", 0), ("balanced", 35), ("bold", 75)):
            bets = [
                policies.auto_act(view, rng=Draws(n), appetite=appetite, weights={"standard": 1})[2]
                for n in range(100)
            ]
            self.assertEqual(sum(bool(bet) for bet in bets), expected)
            self.assertTrue(set(bets) <= {"", "reaching"})

    def test_passives_do_not_run_in_ordinary_checks(self):
        modifier = CombatEffect.from_spec(
            {
                "kind": "combat_bonus",
                "phase": "exchange_end",
                "field": "pressure_recovery",
                "amount": 2,
            }
        )
        self.assertEqual(modifier.hooks(), set())
        modified = Build(build().scores, effects=(("recovery", json.dumps(modifier.frozen())),))
        state = duel(attacker=modified)
        actor = engine.participant(state, 1)
        actor["pressure"] = 30
        token = declare(state)
        engine.reaction(state, 2, token, "evade")
        self.assertEqual(actor["pressure"], 22)


@override_settings(RP_COMBAT_REVEALED=True, RP_COMBAT_FROZEN=False, RP_COMBAT_TACTICS_REVEALED=True)
class TestCoordinator(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        source = patch("evennia_rp_combat.services.snapshot", return_value=build())
        source.start()
        self.addCleanup(source.stop)
        services.setup(self.char1)
        services.join(self.char1, "one")
        services.join(self.char2, "two")

    def test_duplicate_delivery_and_reload_preserve_result(self):
        ex_id = services.declare(
            self.char1, [self.char2], rng=random.Random(7), operation_id="declaration"
        )
        services.declare(
            self.char1, [self.char2], rng=random.Random(999), operation_id="declaration"
        )
        token = f"{ex_id}:1"
        services.react(self.char2, token, "resist", operation_id="reaction")
        first = services.state_for(self.char1)
        services.react(self.char2, token, "resist", operation_id="reaction")
        script = services.coordinator(self.char1.location)
        script.attributes.reset_cache()
        self.assertEqual(services.state_for(self.char1), first)
        self.assertEqual(first["participants"][str(self.char1.pk)]["turns"], 1)
        self.assertEqual(len(first["exchanges"]), 1)

    def test_pause_freeze_keep_cancellation_available(self):
        ex_id = services.declare(self.char1, [self.char2])
        services.storyteller(self.char1, "pause")
        with self.assertRaisesRegex(CombatError, "paused"):
            services.react(self.char2, f"{ex_id}:1", "resist")
        with override_settings(RP_COMBAT_FROZEN=True):
            services.control(self.char2, "cancel", argument=f"{ex_id}:1")
            with self.assertRaisesRegex(CombatError, "frozen"):
                services.auto_act(self.char1)

    def test_failed_operation_is_atomic(self):
        before = services.state_for(self.char1)
        with self.assertRaises(CombatError):
            services.declare(self.char1, [self.char2], empower=True)
        self.assertEqual(services.state_for(self.char1), before)

    def test_auto_resolve_is_explicit_and_uses_shared_path(self):
        ex_id = services.declare(self.char1, [self.char2], rng=random.Random(7))
        self.assertEqual(services.state_for(self.char1)["exchanges"][ex_id]["phase"], "waiting")
        services.control(self.char2, "auto", argument="on")
        state = services.state_for(self.char1)
        self.assertEqual(state["exchanges"][ex_id]["phase"], "done")
        self.assertTrue(state["participants"][str(self.char2.pk)]["auto"])

    def test_staff_rollback_restores_interleaved_costs_and_invalidates_tokens(self):
        ex_id = services.declare(self.char1, [self.char2], operation_id="old-declare")
        script = services.coordinator(self.char1.location)
        sequence = len(script.db.journal) + 1
        services.react(self.char2, f"{ex_id}:1", "resist", operation_id="old-react")
        with (
            patch("evennia_rp_combat.services.staff", return_value=False),
            self.assertRaisesRegex(CombatError, "Only staff"),
        ):
            services.rollback(self.char1, sequence, "Mistaken target")
        with patch("evennia_rp_combat.services.staff", return_value=True):
            services.rollback(self.char1, sequence, "Mistaken target")
        state = services.state_for(self.char1)
        self.assertEqual(state["participants"][str(self.char2.pk)]["hp"], 100)
        with self.assertRaisesRegex(CombatError, "stale"):
            services.react(self.char2, f"{ex_id}:1", "resist")
        with self.assertRaisesRegex(CombatError, "superseded"):
            services.react(self.char2, f"{ex_id}:1", "resist", operation_id="old-react")

    def test_commands_plain_text_and_self_invoked_auto_act(self):
        self.call(CmdCombat(), "", "Combat: active.")
        self.call(
            CmdTactics(),
            '/save Careful={"appetite":"cautious","rps_appetite":"bold"}',
            "Active Tactics: Careful.",
        )
        self.call(CmdCombat(), "/act", "2.")
        state = services.state_for(self.char1)
        self.assertEqual(len(state["exchanges"]), 1)
        self.assertFalse(state["participants"][str(self.char1.pk)]["auto"])

    def test_operation_ids_cannot_be_reused_for_another_actor(self):
        services.control(self.char1, "posed", operation_id="same")
        with self.assertRaisesRegex(CombatError, "different request"):
            services.control(self.char2, "posed", operation_id="same")

    def test_absence_cancels_unaccepted_packets_and_neutrally_fades(self):
        from .maintenance import maintain

        services.declare(self.char1, [self.char2])
        self.char2.location = self.room2
        script = services.coordinator(self.char1.location)
        maintain(script)
        state = services.state_for(self.char1)
        row = state["participants"][str(self.char2.pk)]
        self.assertEqual((row["status"], row["hp"]), ("faded", 100))
        self.assertIsNone(state["participants"][str(self.char1.pk)]["outgoing"])
        self.assertEqual(state["participants"][str(self.char1.pk)]["clock"], 0)

    def test_idle_fades_without_enabling_automation(self):
        from .maintenance import maintain

        script = services.coordinator(self.char1.location)
        now = max(row["last_activity"] for row in script.db.state["participants"].values())
        with override_settings(RP_COMBAT_IDLE_SECONDS=10):
            maintain(script, now=now + 11)
        state = services.state_for(self.char1)
        self.assertTrue(state["paused"])
        self.assertTrue(
            all(
                row["status"] == "faded" and not row["auto"]
                for row in state["participants"].values()
            )
        )

    def test_read_is_private_paid_and_does_not_accept_reaction(self):
        own = Build(build().scores, abilities=(("proficiency", "insight", 1),))
        services.execute(
            self.char2,
            "test build",
            lambda state: state["participants"][str(self.char2.pk)].update(build=own.as_dict()),
        )
        with override_settings(RP_COMBAT_DOMAIN_EFFECTS={"insight": "read"}):
            ex_id = services.declare(self.char1, [self.char2], bet="subtle")
            token = f"{ex_id}:1"
            self.assertNotIn("subtle", services.odds(self.char2, token))
            self.assertIn("RPS subtle", services.read(self.char2, token, "insight"))
            state = services.state_for(self.char2)
            self.assertFalse(state["exchanges"][ex_id]["reactions"])
            self.assertEqual(state["participants"][str(self.char2.pk)]["reserves"], 2)

    def test_actual_pose_acknowledges_without_synthetic_activity(self):
        from .maintenance import note_pose

        ex_id = services.declare(self.char1, [self.char2])
        services.react(self.char2, f"{ex_id}:1", "resist")
        self.assertTrue(services.state_for(self.char1)["participants"][str(self.char1.pk)]["pose"])
        note_pose(None, character=self.char1)
        self.assertFalse(services.state_for(self.char1)["participants"][str(self.char1.pk)]["pose"])

    def test_exhausted_personal_caps_close_without_global_rounds(self):
        services.control(self.char1, "cap", argument=1)
        services.control(self.char2, "cap", argument=1)
        ex_id = services.declare(self.char1, [self.char2])
        services.react(self.char2, f"{ex_id}:1", "resist")
        self.assertFalse(services.state_for(self.char1)["ended"])
        ex_id = services.declare(self.char2, [self.char1])
        services.react(self.char1, f"{ex_id}:1", "resist")
        self.assertTrue(services.state_for(self.char1)["ended"])
        self.assertIsNone(self.char1.attributes.get("build_lock", category="rp_combat"))

    def test_storyteller_commands_do_not_require_staff_or_force_caps(self):
        with patch("evennia_rp_combat.services.staff", return_value=False):
            self.call(CmdCombatStory(), f"/requestcap {self.char2.key}=2;short scene", "")
        row = services.state_for(self.char2)["participants"][str(self.char2.pk)]
        self.assertEqual((row["turn_limit"], row["cap_request"]), (4, 2))
        services.control(self.char2, "acceptcap")
        self.assertEqual(
            services.state_for(self.char2)["participants"][str(self.char2.pk)]["turn_limit"], 2
        )

    def test_nonparticipant_invitation_does_not_spend_or_enroll(self):
        from evennia.utils.create import create_object

        target = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Unenrolled",
            location=self.char1.location,
        )
        before = services.state_for(self.char1)
        services.declare(self.char1, [target])
        self.assertEqual(services.state_for(self.char1), before)
        services.refuse(target)
        self.assertNotIn(str(target.pk), services.state_for(self.char1)["participants"])

    def test_ignore_removal_is_explicit_account_wide_and_mutual(self):
        if not apps.is_installed("evennia_social"):
            self.skipTest("optional social partner absent")
        first, second = self.account, self.account2
        self.char1.db.account, self.char2.db.account = first, second
        first.db.ignore_list, second.db.ignore_list = [second.pk], [first.pk]
        with self.assertRaisesRegex(CombatError, "confirmation"):
            services.declare(self.char1, [self.char2])
        services.unignore(self.char1, self.char2)
        self.assertEqual(first.db.ignore_list, [])
        self.assertEqual(second.db.ignore_list, [first.pk])
        with self.assertRaisesRegex(CombatError, "confirmation"):
            services.declare(self.char1, [self.char2])
        services.unignore(self.char2, self.char1)
        services.declare(self.char1, [self.char2])

    def test_committed_results_survive_reload_without_repeating_writes(self):
        ex_id = services.declare(self.char1, [self.char2], bet="subtle")
        self.assertNotIn("subtle", services.result(self.char1, ex_id))
        services.react(self.char2, f"{ex_id}:1", "resist")
        before = services.state_for(self.char1)
        services.coordinator(self.char1.location).attributes.reset_cache()
        self.assertIn("subtle", services.result(self.char1, ex_id))
        self.assertEqual(before, services.state_for(self.char1))

    def test_burst_press_rechecks_presence_and_ignore(self):
        ex_id = services.declare(self.char1, [self.char2], burst=True, rng=random.Random(2))
        services.react(self.char2, f"{ex_id}:1", "resist")
        before = services.state_for(self.char1)
        self.char2.location = self.room2
        with self.assertRaisesRegex(CombatError, "left the room"):
            services.control(self.char1, "press")
        self.assertEqual(before, services.state_for(self.char1))
        services.control(self.char1, "stop")

    def test_maintenance_and_rollback_publish_membership_seam(self):
        from .maintenance import maintain
        from .signals import membership_changed

        received = []

        def receiver(sender, **kwargs):
            received.append((kwargs["character_id"], kwargs["status"]))

        membership_changed.connect(receiver, weak=False)
        self.addCleanup(membership_changed.disconnect, receiver)
        self.char2.location = self.room2
        with self.captureOnCommitCallbacks(execute=True):
            maintain(services.coordinator(self.char1.location))
        self.assertIn((self.char2.pk, "faded"), received)
        sequence = services.coordinator(self.char1.location).db.journal[-1]["sequence"]
        self.char2.location = self.char1.location
        with (
            patch("evennia_rp_combat.services.staff", return_value=True),
            self.captureOnCommitCallbacks(execute=True),
        ):
            services.rollback(self.char1, sequence, "Restore presence for this test")
        self.assertIn((self.char2.pk, "active"), received)

    def test_unsupported_state_version_preserves_progress(self):
        from .maintenance import maintain

        script = services.coordinator(self.char1.location)
        state = services.clone(script.db.state)
        state["schema"] = 999
        script.db.state = state
        with self.assertRaisesRegex(CombatError, "Unsupported combat state"):
            services.auto_act(self.char1)
        maintain(script)
        self.assertEqual(services.clone(script.db.state), state)

    def test_player_text_is_literal_in_public_mechanics(self):
        text = "{name} $You() |rcolored|n " + "x" * 200
        self.char2.key = text
        with (
            patch.object(self.char1, "msg") as received,
            self.captureOnCommitCallbacks(execute=True),
        ):
            services.declare(self.char1, [self.char2])
        messages = str(received.call_args_list)
        self.assertIn("{name} $You() colored", messages)
        self.assertNotIn("|r", messages)
        self.assertNotIn("\x1b", services.render(self.char2))


class TestConfiguration(SimpleTestCase):
    def test_invalid_numeric_and_domain_configuration_fails_closed(self):
        from .checks import check_configuration

        for values in ({"unknown": 1}, {"resist_fraction": "NaN"}, {"damage_floor": 50}):
            with override_settings(RP_COMBAT_RULES=values):
                self.assertIn("rp_combat.E004", {e.id for e in check_configuration()})
        with override_settings(RP_COMBAT_DOMAIN_EFFECTS={"wrong": "unsupported"}):
            self.assertIn("rp_combat.E005", {e.id for e in check_configuration()})

    def test_passive_counter_power_and_accuracy_use_the_frozen_defender(self):
        spec = {"kind": "combat_bonus", "phase": "declare", "field": "power", "amount": 2}
        own = Build(build().scores, effects=(("counter-power", json.dumps(spec)),))
        state = duel(defender=own)
        token = declare(state, roll=1)
        engine.reaction(state, 2, token, "overpower")
        outcome = next(iter(state["exchanges"].values()))["outcomes"][0]
        self.assertEqual(outcome["counter_damage"], 26)


@skipUnless(apps.is_installed("evennia_npcs"), "optional NPC partner absent")
@override_settings(
    RP_COMBAT_REVEALED=True,
    RP_COMBAT_FROZEN=False,
    NPCS_REVEALED=True,
    NPCS_FROZEN=False,
    NPCS_TYPECLASS="evennia_npcs.typeclasses.NPCCharacter",
)
class TestNPCWithoutSheets(RulesetTestMixin, EvenniaCommandTest):
    from copy import deepcopy

    from evennia_rp_rules.testing import TEST_RULESET

    ruleset_spec = deepcopy(TEST_RULESET)
    ruleset_spec["scales"]["tier"]["rungs"] = [  # noqa: RUF012 - shared immutable test spec
        {"key": key, "label": key.upper(), "score": index * 10}
        for index, key in enumerate(("d", "c", "b", "a", "s"))
    ]
    ruleset_spec["stats"] = [  # noqa: RUF012 - copied by RulesetTestMixin
        {"key": key, "name": key.title()}
        for key in (
            "strength",
            "endurance",
            "intellect",
            "intuition",
            "presence",
            "resolve",
            "agility",
        )
    ]

    def test_real_template_batch_without_any_pc_sheet_or_scene_requirement(self):
        from evennia_npcs import services as npcs

        self.char2.location = self.char1.location
        blueprint = npcs.create_blueprint(
            self.char1,
            "Independent partner",
            "template",
            stat_block={key: "B" for key in self.ruleset.stats},
        )
        services.setup(self.char1)
        with patch("evennia_rp_combat.services.snapshot", return_value=build()):
            services.join(self.char2, "opposition")
        npc = services.template(self.char1, blueprint, "practice")
        row = services.state_for(self.char1)["participants"][str(npc.pk)]
        self.assertEqual(row["build"]["scores"]["attack"], "0")
        self.assertEqual(row["batch_controller"], self.char1.pk)
        services.auto_batch(self.char1, [npc])
        state = services.state_for(self.char1)
        self.assertEqual(len(state["participants"][str(self.char2.pk)]["incoming"]), 1)
        with override_settings(NPCS_FROZEN=True), self.assertRaisesRegex(CombatError, "paused"):
            services.auto_act(self.char1, subject=npc)
