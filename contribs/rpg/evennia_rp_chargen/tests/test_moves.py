# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Free libraries remain independent from combat and equipped build guards."""

from unittest.mock import patch

from django.test import override_settings

from evennia_rp_chargen import guards, moves
from evennia_rp_chargen.move_commands import CmdMoves
from evennia_rp_chargen.services import ChargenError

from .base import ChargenCommandTest


@override_settings(RP_CHARGEN_MOVES_REVEALED=True, RP_CHARGEN_MOVE_VALIDATOR=None)
class TestSignatureLibrary(ChargenCommandTest):
    def test_free_library_equipped_limit_and_stable_revisions(self):
        row = moves.create(self.char1, "Guard", power=1, accuracy=1, effects=["resist_stance"])
        self.assertIsNone(row.equipped_order)
        self.assertEqual(row.revision, 1)
        moves.equip(self.char1, row.key)
        edited = moves.edit(self.char1, row.key, wording="Poised to block.")
        self.assertEqual(edited.revision, 2)
        with override_settings(RP_CHARGEN_MOVE_EQUIPPED_LIMIT=1):
            other = moves.create(self.char1, "Other")
            with self.assertRaisesRegex(ChargenError, "full"):
                moves.equip(self.char1, other.key)
        moves.archive(self.char1, row.key)
        with self.assertRaisesRegex(ChargenError, "already exists"):
            moves.create(self.char1, "Guard")

    def test_equipped_edit_equip_and_archive_respect_partner_guard(self):
        row = moves.create(self.char1, "Guard")
        moves.equip(self.char1, row.key)
        with patch.object(guards, "check", side_effect=ChargenError("Fight-long lock")):
            for action in (
                lambda: moves.edit(self.char1, row.key, wording="Changed"),
                lambda: moves.equip(self.char1, row.key, equipped=False),
                lambda: moves.archive(self.char1, row.key),
            ):
                with self.assertRaisesRegex(ChargenError, "Fight-long"):
                    action()
            unused = moves.create(self.char1, "Unused")
            moves.edit(self.char1, unused.key, wording="Library authoring is free.")

    def test_invalid_authored_tiers_effects_and_fields_fail_before_writes(self):
        for definition in (
            {"power": 4, "accuracy": 0},
            {"power": 5, "accuracy": -3},
            {"effects": ["resist_stance"] * 2},
            {"effects": ["heal"]},
            {"action": "assist", "power": 1},
            {"unknown": True},
        ):
            with self.assertRaises(ChargenError):
                moves.create(self.char1, "Invalid", **definition)
        self.assertFalse(moves.library(self.char1).exists())

    def test_commands_and_runtime_gate(self):
        self.call(
            CmdMoves(),
            '/create Ready={"power":1,"accuracy":1,"effects":["evade_stance"]}',
            "Ready: create complete.",
        )
        self.call(CmdMoves(), "/equip ready", "Ready: equip complete.")
        self.call(CmdMoves(), "", "Ready (ready, revision 1):")
        with override_settings(RP_CHARGEN_MOVES_REVEALED=False):
            self.call(CmdMoves(), "", "Signature Moves are not available yet.")
