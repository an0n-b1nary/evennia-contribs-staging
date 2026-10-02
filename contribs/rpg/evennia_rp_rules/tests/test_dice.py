# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Dice expressions, rollers, and exact distributions."""

from __future__ import annotations

import random
import unittest
from fractions import Fraction

from evennia_rp_rules.dice import DiceSpec, RandomRoller, Roller, ScriptedRoller, distribution


class ParseTests(unittest.TestCase):
    def test_round_trip_and_bounds(self):
        cases = {
            "1d20": ("1d20", 1, 20),
            "d20": ("1d20", 1, 20),
            "2d6-7": ("2d6-7", -5, 5),
            "1d10 - 1d10": ("1d10-1d10", -9, 9),
            "3D6 + 2": ("3d6+2", 5, 20),
            "-1d4": ("-1d4", -4, -1),
            "5": ("5", 5, 5),
        }
        for text, (canonical, low, high) in cases.items():
            with self.subTest(text=text):
                spec = DiceSpec.parse(text)
                self.assertEqual((str(spec), spec.minimum, spec.maximum), (canonical, low, high))
                self.assertEqual(DiceSpec.parse(str(spec)), spec)

    def test_bad_expressions_are_refused(self):
        for text in ("", "   ", "2x6", "0d6", "1d0", "1d6 2", "1d6+", "d", "1d6*2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                DiceSpec.parse(text)

    def test_size_limits(self):
        with self.assertRaises(ValueError):
            DiceSpec.parse("21d6")
        with self.assertRaises(ValueError):
            DiceSpec.parse("1d1001")
        with self.assertRaises(ValueError):
            DiceSpec.parse("3d1000")  # span 2997

    def test_parse_is_idempotent_on_a_spec(self):
        spec = DiceSpec.parse("2d6")
        self.assertIs(DiceSpec.parse(spec), spec)


class DistributionTests(unittest.TestCase):
    def test_every_distribution_sums_to_exactly_one(self):
        for text in ("1d20", "2d6", "1d10-1d10", "3d20-3d20", "4d6+3", "7"):
            with self.subTest(text=text):
                self.assertEqual(sum(distribution(text).values()), 1)

    def test_known_values(self):
        two_d6 = distribution("2d6")
        self.assertEqual(two_d6[7], Fraction(1, 6))
        self.assertEqual(two_d6[2], Fraction(1, 36))
        self.assertEqual(min(two_d6), 2)
        self.assertEqual(max(two_d6), 12)
        self.assertEqual(distribution("5"), {5: Fraction(1)})

    def test_difference_of_equal_dice_is_symmetric(self):
        dist = distribution("1d6-1d6")
        for k in range(1, 6):
            self.assertEqual(dist[k], dist[-k])
            self.assertEqual(dist[k], Fraction(6 - k, 36))

    def test_returned_dict_is_a_copy(self):
        distribution("1d4")[1] = Fraction(0)
        self.assertEqual(distribution("1d4")[1], Fraction(1, 4))


class RollerTests(unittest.TestCase):
    def test_random_roller_is_reproducible_with_a_seeded_rng(self):
        roller_a = RandomRoller(random.Random(7))
        roller_b = RandomRoller(random.Random(7))
        self.assertEqual(
            [roller_a.roll("3d6").total for _ in range(20)],
            [roller_b.roll("3d6").total for _ in range(20)],
        )

    def test_random_roll_faces_add_up(self):
        roller = RandomRoller(random.Random(1))
        for _ in range(200):
            roll = roller.roll("2d6-1d4+1")
            sixes, fours = roll.faces
            self.assertEqual(len(sixes), 2)
            self.assertEqual(len(fours), 1)
            self.assertEqual(roll.total, sum(sixes) - sum(fours) + 1)
            self.assertTrue(roll.spec.minimum <= roll.total <= roll.spec.maximum)

    def test_scripted_roller_returns_totals_in_order(self):
        roller = ScriptedRoller([3, -2, 0])
        self.assertEqual([roller.roll("1d6-1d6").total for _ in range(3)], [3, -2, 0])
        self.assertEqual(roller.remaining, 0)
        self.assertEqual(len(roller.rolled), 3)
        self.assertIsNone(roller.rolled[0].faces)

    def test_scripted_roller_refuses_impossible_totals(self):
        with self.assertRaises(ValueError):
            ScriptedRoller([13]).roll("2d6")
        with self.assertRaises(ValueError):
            ScriptedRoller([1]).roll("2d6")

    def test_scripted_roller_runs_out_loudly(self):
        roller = ScriptedRoller([4])
        roller.roll("1d6")
        with self.assertRaises(LookupError):
            roller.roll("1d6")

    def test_rollers_satisfy_the_protocol(self):
        self.assertIsInstance(RandomRoller(), Roller)
        self.assertIsInstance(ScriptedRoller([]), Roller)


if __name__ == "__main__":
    unittest.main()
