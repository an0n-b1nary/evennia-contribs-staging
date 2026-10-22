# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Give-style quantities and comments retain the adjustment audit trail."""

from unittest import skipUnless

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdResources
from .models import PlotThreadResourcePayout, ResourceDefinition, ResourceGrant, ResourceHolding
from .services import total_held


@override_settings(RP_RESOURCES_REVEALED=True)
class ResourceSyntaxTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        ResourceDefinition.objects.create(key="syntax-timber", name="Timber", category="materials")

    def test_grant_and_spend_preserve_comments_and_staff_identity(self):
        note = "For #12.3: A=B, C; keep # this CASE"
        self.call(
            CmdResources(), f"/GR #{self.char2.pk}=10 syntax-timber # {note}", "Resources updated"
        )
        self.call(CmdResources(), "/SP Char2=2 syntax-timber # Used", "Resources updated")
        self.assertEqual(total_held(self.char2), 8)
        rows = list(ResourceGrant.objects.order_by("pk"))
        self.assertEqual(
            [(row.quantity, row.note, row.by_id) for row in rows],
            [(10, note, self.char1.pk), (-2, "Used", self.char1.pk)],
        )

    def test_old_forms_bad_quantities_and_switches_cannot_adjust(self):
        for args in (
            "/grant Char2=syntax-timber,4,Old note",
            "/spend Char2=syntax-timber,2,Old note",
            "/grant/audit Char2=syntax-timber,4,Old note",
            "/grant/typo Char2=syntax-timber,4,Old note",
            "/p Char2=4 syntax-timber",
            "/typo Char2=4 syntax-timber",
            "/grant Char2=0 syntax-timber",
            "/grant Char2=-1 syntax-timber",
            "/grant Char2=2.5 syntax-timber",
            "/grant Char2=4 syntax-timber,Note",
        ):
            with self.subTest(args=args):
                self.call(CmdResources(), args)
                self.assertFalse(ResourceGrant.objects.exists())
                self.assertFalse(ResourceHolding.objects.exists())

    def test_optional_note_keeps_default_and_player_cannot_grant(self):
        self.call(CmdResources(), "/grant Char2=3 syntax-timber", "Resources updated")
        self.assertEqual(ResourceGrant.objects.get().note, "Staff adjustment")
        self.call(
            CmdResources(), "/grant Char2=4 syntax-timber # No", "Only staff", caller=self.char2
        )
        self.assertEqual(total_held(self.char2), 3)
        self.assertEqual(ResourceGrant.objects.count(), 1)

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    def test_plot_number_proposal_and_approval_preserve_owner_permissions(self):
        from evennia_plots.models import PlotThread

        plot = PlotThread.create_thread("Syntax budget", self.char2)
        self.call(CmdResources(), f"/payout #{plot.plot_number}=syntax-timber,4", caller=self.char2)
        self.assertFalse(PlotThreadResourcePayout.objects.exists())
        self.call(
            CmdResources(),
            f"/payout #{plot.plot_number}=4 syntax-timber",
            "Payout proposed",
            caller=self.char2,
        )
        row = PlotThreadResourcePayout.objects.get()
        self.assertEqual(
            (row.thread_id, row.quantity, row.set_by_id, row.approved_by_id),
            (plot.pk, 4, self.char2.pk, None),
        )
        self.call(
            CmdResources(),
            f"/payoutapprove #{plot.plot_number}",
            "Only plot owners or staff",
            caller=self.char2,
        )
        row.refresh_from_db()
        self.assertIsNone(row.approved_by_id)
        self.call(CmdResources(), f"/payoutapprove #{plot.plot_number}", "Approved 1")
        row.refresh_from_db()
        self.assertEqual(row.approved_by_id, self.char1.pk)
