# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_channel, create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from . import services
from .behaviours import behaviour
from .commands import CmdCraft, CmdUse
from .errors import CraftingError
from .events import use
from .models import CraftRecord, EventChannelLimit, EventRoomLimit, EventUse, NicheDefinition
from .tests import CraftingFixture

HAS_ACCESSIBILITY = apps.is_installed("evennia_accessibility")


class EventFixture(CraftingFixture):
    def setUp(self):
        super().setUp()
        override = override_settings(
            RP_CRAFTING_EVENT_ROOM_COOLDOWN=30,
            RP_CRAFTING_EVENT_FRAME="<EVENT> {text}",
            RP_CRAFTING_CHANNELS=("Effects",),
        )
        override.enable()
        self.addCleanup(override.disable)
        for key, kind, category in (
            ("cooking", "consumable", "provisions"),
            ("illusions", "broadcast", "essences"),
        ):
            NicheDefinition.objects.create(
                key=key,
                name=key.title(),
                behaviours=[kind],
                input_categories=[category],
                unlock_resources={category: 3},
                unlock_money=0,
            )
        services.unlock(self.char1, "cooking", {"grain": 3})
        services.unlock(self.char1, "illusions", {"spark": 6})

    def item(self, kind="consumable", **configuration):
        return services.craft(
            self.char1,
            "cooking" if kind == "consumable" else "illusions",
            kind,
            "test cake" if kind == "consumable" else "test globe",
            "A test item.",
            {"beats": ["Golden sparks bloom."], **configuration},
            {"grain" if kind == "consumable" else "spark": len(configuration.get("beats", [1]))},
        )

    def expire(self):
        EventRoomLimit.objects.update(last_used=timezone.now() - timedelta(seconds=31))
        EventChannelLimit.objects.update(last_used=timezone.now() - timedelta(seconds=31))

    def unmute(self, account):
        # Host-independent tests still exercise the actual OptionHandler.
        account.options.options_dict = dict(account.options.options_dict)
        account.options.options_dict["mute_ambient_effects"] = ("Ambient effects", "Boolean", False)
        account.options.set("mute_ambient_effects", "False")


class EventTests(EventFixture, EvenniaTest):
    def test_consumes_once_and_keeps_canonical_prose_after_deletion(self):
        item = self.item(beats=["First light.", "Then darkness."])
        item_id, record_id = item.pk, item.craft_record.pk
        item.db.beats = ["Forged message."]
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            result = use(self.char1, item)
        msg.assert_called_once_with(
            "<EVENT> First light.\n<EVENT> Then darkness.", options={"type": "crafting_event"}
        )
        self.assertFalse(ObjectDB.objects.filter(pk=item_id).exists())
        self.assertEqual(result.craft_id, record_id)
        self.assertTrue(CraftRecord.objects.filter(pk=record_id).exists())
        with self.assertRaises(CraftingError):
            use(self.char1, item)
        self.assertEqual(EventUse.objects.count(), 1)

    def test_rate_limit_refuses_second_item_without_consuming_it_and_expires(self):
        first, second = self.item(), self.item()
        use(self.char1, first)
        with self.assertRaisesMessage(CraftingError, "Wait a moment"):
            use(self.char1, second)
        self.assertTrue(ObjectDB.objects.filter(pk=second.pk).exists())
        self.assertEqual(EventUse.objects.count(), 1)
        self.expire()
        use(self.char1, second)
        self.assertEqual(EventUse.objects.count(), 2)

    def test_room_limit_is_shared_between_characters(self):
        first, second = self.item(), self.item()
        second.move_to(self.char2, quiet=True)
        use(self.char1, first)
        with self.assertRaises(CraftingError):
            use(self.char2, second)

    def test_plain_items_and_unheld_or_locked_crafts_cannot_emit(self):
        plain = create_object(location=self.char1)
        plain.db.beats = ["Forged"]
        with self.assertRaisesMessage(CraftingError, "Only crafted"):
            use(self.char1, plain)
        item = self.item()
        item.locks.add("use:false()")
        with self.assertRaises(CraftingError):
            use(self.char2, item)
        with self.assertRaises(CraftingError):
            use(self.char1, item)
        self.assertFalse(EventUse.objects.exists())

    def test_freeze_hide_and_bad_frame_preserve_item(self):
        item = self.item()
        for kwargs in (
            {"RP_CRAFTING_FROZEN": True},
            {"RP_CRAFTING_REVEALED": False},
            {"RP_CRAFTING_EVENT_FRAME": "{unknown}"},
        ):
            with override_settings(**kwargs), self.assertRaises(CraftingError):
                use(self.char1, item)
        self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())
        self.assertFalse(EventUse.objects.exists())

    def test_refused_deletion_rolls_back_claim_limits_and_notifications(self):
        item = self.item()
        with (
            patch.object(item, "delete", return_value=False),
            patch.object(self.char2, "msg") as msg,
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaises(CraftingError),
        ):
            use(self.char1, item)
        self.assertFalse(EventUse.objects.exists())
        self.assertFalse(EventRoomLimit.objects.exists())
        msg.assert_not_called()

    def test_outer_rollback_discards_delivery_and_restores_consumed_object(self):
        item = self.item()
        item_id = item.pk
        with (
            patch.object(self.char2, "msg") as msg,
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaises(RuntimeError),
            transaction.atomic(),
        ):
            use(self.char1, item)
            raise RuntimeError("host rollback")
        msg.assert_not_called()
        self.assertTrue(ObjectDB.objects.filter(pk=item_id).exists())
        self.assertFalse(EventUse.objects.exists())

    def test_delivery_failure_does_not_undo_consumption(self):
        item = self.item()
        with (
            patch.object(self.char2, "msg", side_effect=RuntimeError("offline")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, item)
        self.assertEqual(EventUse.objects.count(), 1)

    def test_delivery_uses_current_audience_after_outer_commit(self):
        item = self.item()
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, item)
            self.char2.move_to(self.room2, quiet=True)
            msg.reset_mock()
        msg.assert_not_called()

    def test_cost_each_extra_beat_and_reject_invalid_prose_before_spending(self):
        cost = behaviour("consumable").cost("consumable", {"beats": ["a", "b", "c"]})
        self.assertEqual(cost, {"provisions": 3})
        before = self.held("grain")
        for beats in ([], ["a"] * 4, ["x" * 401], ["a\nb"], ["|rspoof"], ["<EVENT> spoof"], [""]):
            with self.assertRaises(CraftingError):
                self.item(beats=beats)
        self.assertEqual(self.held("grain"), before)

    def test_adjacent_reach_respects_mute_and_does_not_recurse(self):
        create_object(
            "evennia.objects.objects.DefaultExit", location=self.room1, destination=self.room2
        )
        create_object(
            "evennia.objects.objects.DefaultExit", location=self.room1, destination=self.room2
        )
        self.char2.move_to(self.room2, quiet=True)
        if HAS_ACCESSIBILITY:
            self.unmute(self.account2)
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item("broadcast"))
        self.assertEqual(msg.call_count, 1 if HAS_ACCESSIBILITY else 0)
        self.expire()
        if HAS_ACCESSIBILITY:
            self.account2.options.set("mute_ambient_effects", "True")
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item("broadcast"))
        msg.assert_not_called()

    def test_muted_local_scene_is_still_delivered(self):
        if HAS_ACCESSIBILITY:
            self.unmute(self.account2)
            self.account2.options.set("mute_ambient_effects", "True")
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item("broadcast"))
        self.assertEqual(msg.call_count, 1)

    def test_locked_exit_does_not_leak_event(self):
        create_object(
            "evennia.objects.objects.DefaultExit", location=self.room1, destination=self.room2
        )
        for candidate in self.room1.exits:
            candidate.locks.add("traverse:false()")
        self.char2.move_to(self.room2, quiet=True)
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item("broadcast"))
        msg.assert_not_called()

    def test_channel_effect_is_muted_and_not_duplicated_in_source_room(self):
        if not HAS_ACCESSIBILITY:
            self.skipTest("accessibility absent; own-room only")
        channel = create_channel("Effects", locks="send:all();listen:all()")
        channel.connect(self.account2)
        self.unmute(self.account2)
        self.account2.options.set("mute_ambient_effects", "True")
        with (
            patch.object(self.char2, "msg") as local,
            patch.object(self.account2, "msg") as remote,
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item("broadcast", reach="channel", channel="Effects"))
        self.assertEqual(local.call_count, 1)
        remote.assert_not_called()
        self.expire()
        self.char2.move_to(self.room2, quiet=True)
        with (
            patch.object(self.account2, "msg") as remote,
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item("broadcast", reach="channel", channel="Effects"))
        remote.assert_not_called()

        self.expire()
        self.account2.options.set("mute_ambient_effects", "False")
        channel.mute(self.account2)
        with (
            patch.object(self.account2, "msg") as remote,
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item("broadcast", reach="channel", channel="Effects"))
        remote.assert_not_called()

    def test_outside_room_is_not_reached_recursively(self):
        third = create_object("evennia.objects.objects.DefaultRoom", key="Third room")
        create_object("evennia.objects.objects.DefaultExit", location=self.room2, destination=third)
        self.char2.move_to(third, quiet=True)
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item("broadcast"))
        msg.assert_not_called()

    def test_adjacent_audience_shares_cooldown_with_source(self):
        if not HAS_ACCESSIBILITY:
            self.skipTest("accessibility absent; own-room only")
        create_object(
            "evennia.objects.objects.DefaultExit", location=self.room1, destination=self.room2
        )
        first, second = self.item("broadcast"), self.item()
        use(self.char1, first)
        self.char1.move_to(self.room2, quiet=True)
        with self.assertRaises(CraftingError):
            use(self.char1, second)

    def test_channel_permissions_allowlist_mute_and_channel_cooldown(self):
        channel = create_channel("Effects", locks="send:all();listen:all()")
        channel.connect(self.account2)
        self.char2.move_to(self.room2, quiet=True)
        if HAS_ACCESSIBILITY:
            self.unmute(self.account2)
        item = self.item("broadcast", reach="channel", channel="Effects")
        with patch.object(self.account2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, item)
        self.assertEqual(msg.call_count, 1 if HAS_ACCESSIBILITY else 0)
        if not HAS_ACCESSIBILITY:
            return
        second = self.item("broadcast", reach="channel", channel="Effects")
        self.char1.move_to(self.room2, quiet=True)
        with self.assertRaisesMessage(CraftingError, "channel"):
            use(self.char1, second)
        self.expire()
        channel.locks.add("send:false()")
        with self.assertRaises(CraftingError):
            use(self.char1, second)
        channel.locks.add("send:all()")
        with override_settings(RP_CRAFTING_CHANNELS=()), self.assertRaises(CraftingError):
            use(self.char1, second)


class EventCommandTests(EventFixture, EvenniaCommandTest):
    def test_compose_preview_remove_beat_and_use_through_commands(self):
        self.call(CmdCraft(), "/new cooking/consumable = command cake", "Craft draft saved")
        self.call(CmdCraft(), "/desc = A tiny cake.", "Craft draft saved")
        self.call(CmdCraft(), "/beat = Warm spice fills the air.", "Craft draft saved")
        self.call(CmdCraft(), "/beat = An extra beat.", "Craft draft saved")
        self.call(CmdCraft(), "/unbeat 2", "Craft draft saved")
        self.call(CmdCraft(), "/resources = grain:1", "Craft draft saved")
        self.call(CmdCraft(), "", "Draft: command cake")
        self.call(CmdCraft(), "/finish", "You craft command cake")
        self.call(CmdUse(), "command cake", "You use command cake")
        self.assertEqual(EventUse.objects.count(), 1)

    def test_beat_errors_name_the_beat(self):
        self.call(CmdCraft(), "/new cooking/consumable = command cake", "Craft draft saved")
        self.call(CmdCraft(), "/beat = " + "x" * 401, "EVENT beat must contain 1-400 characters.")

    def test_requirement_errors_still_name_the_requirement(self):
        if not apps.is_installed("evennia_rp_equipment"):
            self.skipTest("equipment absent")
        self.call(CmdCraft(), "/new weaving/wearable = command cloak", "Craft draft saved")
        self.call(CmdCraft(), "/require = ", "Requirement must contain 1-200 characters.")
