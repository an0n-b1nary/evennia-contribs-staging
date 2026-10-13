# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Award authority, frozen membership, rollback and recovery under real Plots."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import transaction
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import payouts
from .commands import CmdResources
from .models import (
    PlotPayoutReceipt,
    PlotPayoutRun,
    PlotThreadResourcePayout,
    ResourceDefinition,
    ResourceGrant,
)
from .services import ResourceError, grant, total_held
from .summary import notify_plot_summary


def nobody(character):
    return False


@skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
@override_settings(RP_ECONOMY_ELIGIBLE=None, RP_RESOURCES_REVEALED=True)
class PayoutTests(EvenniaCommandTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        from evennia_plots.models import PlotParticipant, PlotThread

        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.plot = PlotThread.create_thread("A shared expedition", self.char2)
        self.participant = PlotParticipant.objects.create(
            thread=self.plot, character=self.char2, character_name=self.char2.key
        )
        ResourceDefinition.objects.create(
            key="rare", name="Rare crystal", category="essences", in_trickle=False
        )
        ResourceDefinition.objects.create(key="wood", name="Wood", category="materials")

    def budget(self):
        payouts.propose(self.char2, self.plot.pk, "rare", 4)
        payouts.approve(self.char1, self.plot.pk)

    def conclude(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.plot.conclude(concluded_by=self.char2)
        return PlotPayoutRun.objects.get(thread_id=self.plot.pk)

    def test_owner_proposes_but_cannot_approve(self):
        payouts.propose(self.char2, self.plot.pk, "rare", 4)
        with self.assertRaises(ResourceError):
            payouts.approve(self.char2, self.plot.pk)
        with self.assertRaises(ResourceError):
            self.plot.conclude()
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, "proposed")
        self.assertFalse(PlotPayoutRun.objects.exists())
        self.assertEqual(total_held(self.char2), 0)
        payouts.approve(self.char1, self.plot.pk)
        payouts.propose(self.char2, self.plot.pk, "rare", 5)
        self.assertIsNone(PlotThreadResourcePayout.objects.get().approved_by_id)

    def test_coowner_can_propose_but_unrelated_character_cannot(self):
        from evennia.utils.create import create_object
        from evennia_plots.models import PlotOwner

        coowner = create_object("evennia.objects.objects.DefaultCharacter", key="Co-owner")
        outsider = create_object("evennia.objects.objects.DefaultCharacter", key="Outsider")
        PlotOwner.objects.create(plot=self.plot, character=coowner, character_name=coowner.key)
        payouts.propose(coowner, self.plot.pk, "wood", 2)
        self.assertEqual(PlotThreadResourcePayout.objects.get().set_by_id, coowner.pk)
        with self.assertRaises(ResourceError):
            payouts.propose(outsider, self.plot.pk, "wood", 100)
        with self.assertRaises(ResourceError):
            payouts.approve(coowner, self.plot.pk)

    def test_owner_without_participation_is_not_paid(self):
        self.participant.delete()
        self.budget()
        run = self.conclude()
        self.assertEqual(run.recipients, [])
        self.assertEqual(total_held(self.char2), 0)

    def test_guest_is_excluded_even_when_marked_an_active_participant(self):
        self.budget()
        self.char2.tags.add("character", category="guest")
        with self.assertRaises(ResourceError):
            payouts.propose(self.char2, self.plot.pk, "wood", 2)
        self.assertEqual(self.conclude().recipients, [])
        self.assertEqual(total_held(self.char2), 0)

    def test_active_eligible_offline_participant_gets_full_award_above_cap(self):
        grant(self.char2, "wood", 100)
        self.budget()
        self.conclude()
        self.assertEqual(total_held(self.char2), 104)
        grant_row = ResourceGrant.objects.get(source="payout")
        self.assertEqual(grant_row.thread_id, self.plot.pk)
        self.assertEqual(grant_row.by_id, self.char1.pk)

    def test_inactive_and_ineligible_participants_are_excluded(self):
        self.budget()
        self.participant.is_active = False
        self.participant.save()
        run = self.conclude()
        self.assertEqual(run.recipients, [])

    @override_settings(RP_ECONOMY_ELIGIBLE=nobody)
    def test_host_eligibility_is_authoritative(self):
        self.budget()
        self.assertEqual(self.conclude().recipients, [])

    def test_late_participant_and_new_budget_do_not_change_frozen_award(self):
        from evennia_plots.models import PlotParticipant

        self.budget()
        run = self.conclude()
        PlotParticipant.objects.create(
            thread=self.plot, character=self.char1, character_name=self.char1.key
        )
        with self.assertRaises(ResourceError):
            payouts.propose(self.char1, self.plot.pk, "wood", 3)
        self.assertEqual(payouts.retry(self.char1, self.plot.pk)["paid"], [])
        self.assertEqual(total_held(self.char1), 0)
        self.assertEqual(total_held(self.char2), 4)
        self.assertEqual(len(run.recipients), 1)
        self.plot.conclude()
        self.assertEqual(ResourceGrant.objects.filter(source="payout").count(), 1)

    def test_failed_delivery_rolls_back_whole_recipient_then_retry_pays_once(self):
        self.budget()
        payouts.propose(self.char2, self.plot.pk, "wood", 2)
        payouts.approve(self.char1, self.plot.pk)
        real_grant = payouts.grant

        def fail_second(character, key, *args, **kwargs):
            if key == "wood":
                raise ResourceError("Temporary failure")
            return real_grant(character, key, *args, **kwargs)

        with patch.object(payouts, "grant", side_effect=fail_second):
            self.conclude()
        self.assertEqual(total_held(self.char2), 0)
        self.assertFalse(ResourceGrant.objects.filter(source="payout").exists())
        self.assertIsNone(PlotPayoutReceipt.objects.get().paid_at)
        self.assertEqual(payouts.retry(self.char1, self.plot.pk)["paid"], [self.char2.pk])
        payouts.retry(self.char1, self.plot.pk)
        self.assertEqual(total_held(self.char2), 6)

    def test_frozen_award_survives_resource_archival_and_eligibility_change(self):
        self.budget()
        with patch.object(payouts, "deliver"):
            self.conclude()
        ResourceDefinition.objects.filter(key="rare").update(archived=True)
        with override_settings(RP_ECONOMY_ELIGIBLE=nobody):
            payouts.retry(self.char1, self.plot.pk)
        self.assertEqual(total_held(self.char2), 4)

    def test_historical_plot_cannot_be_backfilled(self):
        type(self.plot).objects.filter(pk=self.plot.pk).update(status="concluded")
        with self.assertRaisesRegex(ResourceError, "historical"):
            payouts.retry(self.char1, self.plot.pk)
        with self.assertRaises(ResourceError):
            payouts.propose(self.char1, self.plot.pk, "wood", 2)

    def test_outer_rollback_restores_plot_and_prevents_award_delivery(self):
        self.budget()
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.plot.conclude()
            raise RuntimeError("Later required listener failed")
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, "proposed")
        self.assertFalse(PlotPayoutRun.objects.exists())
        self.assertEqual(total_held(self.char2), 0)

    def test_login_summary_is_once_and_hidden_awards_remain_unseen(self):
        self.budget()
        self.conclude()
        with patch.object(self.char2, "msg") as message:
            with override_settings(RP_RESOURCES_REVEALED=False):
                self.assertFalse(notify_plot_summary(self.char2))
            self.assertTrue(notify_plot_summary(self.char2))
            self.assertFalse(notify_plot_summary(self.char2))
        self.assertEqual(message.call_count, 1)
        self.assertIn("4 rare", message.call_args.args[0])

    def test_commands_require_approval_and_handle_conclusion_error(self):
        from evennia_plots.commands import CmdPlot

        self.call(
            CmdResources(),
            f"/payout {self.plot.pk}=rare,4",
            "Payout proposed; staff approval is required.",
            caller=self.char2,
        )
        self.call(
            CmdPlot(),
            f"/conclude #{self.plot.plot_number}",
            "Approve all payout resources before concluding this plot.",
            caller=self.char2,
        )
        self.call(
            CmdResources(),
            f"/payoutapprove {self.plot.pk}",
            "Approved 1 payout resources.",
            caller=self.char1,
        )

    def test_deleted_frozen_recipient_is_skipped_without_reallocation(self):
        self.budget()
        with patch.object(payouts, "deliver"):
            self.conclude()
        recipient_id = self.char2.pk
        # Character deletion has unrelated host ownership guards; simulate the
        # missing soft reference directly without touching another participant.
        PlotPayoutReceipt.objects.update(character_id=2**31)
        result = payouts.retry(self.char1, self.plot.pk)
        self.assertEqual(result["skipped"], [2**31])
        self.assertEqual(total_held(self.char2), 0)
        self.assertEqual(PlotPayoutRun.objects.get().recipients[0]["character_id"], recipient_id)
