# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Modifier offer lifecycle, input errors and installed-fixture lock order."""

from datetime import timedelta
from unittest import skipUnless

from django.apps import apps
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from . import fixtures, modifiers
from .errors import CraftingError
from .models import ModificationLayer, ModificationOffer
from .test_wave_three import WaveThreeFixture
from .test_wave_two import WaveTwoFixture
from .wave_three_commands import CmdModify


@skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
class ModifierLifecycleTests(WaveThreeFixture, EvenniaCommandTest):
    def test_list_reports_economy_cancellation_without_mutating_service(self):
        from evennia_economy.exchange import cancel_offer

        row = self.offer()
        cancel_offer(self.char2, row.economy_offer_id)
        output = self.call(CmdModify(), "", caller=self.char2)
        self.assertIn("[cancelled]", output)
        row.refresh_from_db()
        self.assertIsNone(row.cancelled_at)

    def test_list_uses_both_deadlines_and_persisted_economy_expiry(self):
        from evennia_economy.models import Offer

        for source in ("service", "economy_deadline", "economy_status"):
            with self.subTest(source=source):
                row = self.offer()
                past = timezone.now() - timedelta(seconds=1)
                if source == "service":
                    ModificationOffer.objects.filter(pk=row.pk).update(expires_at=past)
                elif source == "economy_deadline":
                    Offer.objects.filter(pk=row.economy_offer_id).update(expires=past)
                else:
                    Offer.objects.filter(pk=row.economy_offer_id).update(status="expired")
                economy_status = Offer.objects.get(pk=row.economy_offer_id).status
                output = self.call(CmdModify(), "", caller=self.char2)
                self.assertIn("[expired]", output)
                self.assertEqual(Offer.objects.get(pk=row.economy_offer_id).status, economy_status)
                row.refresh_from_db()
                self.assertIsNone(row.cancelled_at)
                ModificationOffer.objects.filter(pk=row.pk).delete()

    def test_list_labels_open_and_preserves_completed_and_cancelled_precedence(self):
        row = self.offer()
        self.assertIn("[open]", self.call(CmdModify(), ""))
        modifiers.accept(self.char2, row.pk)
        ModificationOffer.objects.filter(pk=row.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIn("[completed]", self.call(CmdModify(), ""))
        other = self.offer(target=self.char2, modifier_key="modifier_mark")
        modifiers.cancel(self.char1, other.pk)
        ModificationOffer.objects.filter(pk=other.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIn("[cancelled]", self.call(CmdModify(), ""))

    def test_either_party_can_close_an_already_cancelled_or_expired_offer(self):
        from evennia_economy.models import Offer

        for actor in (self.char1, self.char2):
            for status in ("cancelled", "expired"):
                with self.subTest(actor=actor.pk, status=status):
                    row = self.offer()
                    Offer.objects.filter(pk=row.economy_offer_id).update(status=status)
                    self.call(
                        CmdModify(),
                        f"/cancel {row.pk}",
                        f"Service #{row.pk} cancelled.",
                        caller=actor,
                    )
                    row.refresh_from_db()
                    self.assertIsNotNone(row.cancelled_at)
                    self.assertFalse(ModificationLayer.objects.filter(service=row).exists())
                    self.assertEqual(Offer.objects.get(pk=row.economy_offer_id).status, status)

    def test_repeated_cancellation_preserves_the_first_timestamp(self):
        row = self.offer()
        modifiers.cancel(self.char2, row.pk)
        row.refresh_from_db()
        first = row.cancelled_at
        modifiers.cancel(self.char1, row.pk)
        row.refresh_from_db()
        self.assertEqual(row.cancelled_at, first)

    def test_cancellation_refuses_unrelated_actor_and_completed_service(self):
        row = self.offer(
            customer=self.char1, target=self.char1, modifier_key="modifier_mark", commission=0
        )
        with self.assertRaises(CraftingError):
            modifiers.cancel(self.char2, row.pk)
        modifiers.accept(self.char1, row.pk)
        with self.assertRaises(CraftingError):
            modifiers.cancel(self.char1, row.pk)
        row.refresh_from_db()
        self.assertIsNone(row.cancelled_at)

    def test_self_service_expiry_is_visible(self):
        row = self.offer(
            customer=self.char1, target=self.char1, modifier_key="modifier_mark", commission=0
        )
        ModificationOffer.objects.filter(pk=row.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIn("[expired]", self.call(CmdModify(), ""))


class ModifierInputTests(WaveThreeFixture, EvenniaCommandTest):
    def test_malformed_service_and_layer_numbers_have_usage_errors(self):
        for switch in ("accept", "cancel", "hide", "show"):
            for value in ("abc", "", "0", "-1", "1.5", str(2**63)):
                with self.subTest(switch=switch, value=value):
                    output = self.call(CmdModify(), f"/{switch} {value}")
                    self.assertIn("Use a", output)
                    self.assertIn("number", output)
                    self.assertNotIn("invalid literal", output)

    def test_malformed_commission_and_replacement_have_specific_errors(self):
        prefix = f"/offer {self.char2.key}/{self.item.key} = layers/modifier_aura"
        for terms, message in (
            ("line ; spark:1 ; abc", "Use a nonnegative whole-number commission"),
            (
                "line; with punctuation ; spark:1 ; abc ; 3",
                "Use a nonnegative whole-number commission",
            ),
            ("line ; spark:1 ; 0 ; abc", "Use a layer number"),
            ("line ; spark:1 ; 0 ; 0", "Use a layer number"),
            ("line ; spark:1 ; -2", "Use a nonnegative whole-number commission"),
        ):
            with self.subTest(terms=terms):
                self.call(CmdModify(), f"{prefix} ; {terms}", message)
        self.assertFalse(ModificationOffer.objects.exists())

    def test_undo_layer_and_commission_have_usage_errors(self):
        prefix = f"/undo {self.char2.key}/{self.item.key} = layers"
        self.call(CmdModify(), f"{prefix} ; abc ; spark:1 ; 0", "Use a layer number")
        self.call(
            CmdModify(),
            f"{prefix} ; 1 ; spark:1 ; abc",
            "Use a nonnegative whole-number commission",
        )


@skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
class ModifierFixtureLockTests(WaveThreeFixture, WaveTwoFixture, EvenniaTest):
    def test_self_service_locks_property_before_any_character_write(self):
        item = self.fixture()
        fixtures.install(self.char1, item, self.room1)
        row = self.offer(customer=self.char1, target=item, commission=0)
        events = []

        def lock(room):
            self.assertEqual(room.pk, self.room1.pk)
            events.append("property")

        def record(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("UPDATE") and '"objects_objectdb"' in sql:
                events.append("object-write")
            return execute(sql, params, many, context)

        with override_settings(LINKS_ROOM_LOCK=lock), connection.execute_wrapper(record):
            modifiers.accept(self.char1, row.pk)
        self.assertIn("object-write", events)
        self.assertEqual(events[0], "property")
        self.assertEqual(ModificationLayer.objects.filter(service=row).count(), 1)
