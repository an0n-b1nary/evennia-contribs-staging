# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cross-state regressions from the first independent foundation review."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import override_settings

from evennia_links.ignoring import ignore_mode_requested, notify_ignore_policy_changing
from evennia_links.notices import ActorRef, Evaluation, NoticeContext, RenderedNotice
from evennia_notices.models import DeliveryReceipt, Notice
from evennia_notices.models import NoticeEvent as Stored
from evennia_notices.services import maintain, mutate, project, route, set_preference

from .test_services import ServicesTests, Source


class ReviewRepairs(ServicesTests):
    """Tests deliberately exercise shared ownership and compacted mixed states."""

    def test_implicit_character_emission_honors_unique_owner_preference(self):
        set_preference(self.context, "test", "off")
        self.assertEqual(route(self.char1, source="test", event=self.event()).status, "suppressed")

    def test_shared_character_off_does_not_suppress_other_owner(self):
        self.account2.characters.add(self.char1)
        set_preference(self.context, "test", "off")
        self.emit(recipient=self.char1)
        self.assertEqual(project(self.context), [])
        self.assertEqual(len(project(NoticeContext(self.account2, self.char1))), 1)

    def test_shared_unignore_preserves_other_owner_and_durable_viewer_suppression(self):
        self.account2.characters.add(self.char1)
        self.emit(self.event(actors=(ActorRef("character", self.char2.pk),)), recipient=self.char1)

        def policy(viewer, **kwargs):
            return "hide" if viewer == self.account else None

        ignore_mode_requested.connect(policy, weak=False)
        try:
            notify_ignore_policy_changing(self.account)
        finally:
            ignore_mode_requested.disconnect(policy)
        self.assertEqual(project(self.context), [])
        self.assertEqual(len(project(NoticeContext(self.account2, self.char1))), 1)
        self.assertEqual(Stored.objects.count(), 1)

    def test_context_deferred_ignored_event_is_suppressed_before_unignore(self):
        def policy(**kwargs):
            return "hide"

        ignore_mode_requested.connect(policy, weak=False)
        try:
            result = route(
                self.account,
                source="test",
                event=self.event(
                    actors=(ActorRef("character", self.char2.pk),),
                    payload={"requires_character": True},
                ),
            )
        finally:
            ignore_mode_requested.disconnect(policy)
        self.assertEqual(result.status, "suppressed")
        self.assertEqual(project(self.context), [])

    @override_settings(NOTICES_ROUTINE_LIMIT=2)
    def test_compacted_slot_replaces_constituent_and_preserves_source_key(self):
        self.emit(self.event("old", replacement_key="slot"))
        self.emit(self.event("b"))
        self.emit(self.event("c"))
        self.emit(self.event("new", replacement_key="slot"))
        ids = {e.event_id for p in project(self.context) for e in p.events}
        self.assertNotIn("old", ids)
        from evennia_notices.services import _stored

        new = Stored.objects.select_related("notice__recipient").get(event_id="new")
        self.assertEqual(_stored(new).replacement_key, "slot")

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_read_and_clear_mutate_all_currently_eligible_compacted_constituents(self):
        self.emit(self.event("a"))
        self.emit(self.event("b", payload={"requires_character": True}))
        token = Notice.objects.get().public_ref
        mutate(NoticeContext(self.account), token, "read")
        mutate(self.context, token, "read")
        self.assertFalse(Stored.objects.filter(read_at__isnull=True).exists())
        mutate(self.context, token, "clear")
        self.assertFalse(Stored.objects.filter(cleared_at__isnull=True).exists())

    def test_retention_uses_first_acknowledgement_even_after_recent_clear(self):
        self.emit()
        token = Notice.objects.get().public_ref
        Stored.objects.update(read_at=self.now - timedelta(days=31))
        mutate(self.context, token, "clear")
        maintain(self.now)
        self.assertFalse(Stored.objects.exists())

    def test_clear_initializes_read_clock_and_context_deferred_routine_history_prunes(self):
        self.emit(self.event(payload={"requires_account": True}), recipient=self.char1)
        mutate(self.context, Notice.objects.get().public_ref, "clear")
        self.assertIsNotNone(Stored.objects.get().read_at)
        Stored.objects.update(read_at=self.now - timedelta(days=31))
        maintain(self.now)
        self.assertFalse(Stored.objects.exists())

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_immediate_at_compaction_threshold_sends_only_new_event(self):
        self.emit(self.event("old"))
        set_preference(self.context, "test", "immediate")
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        context = NoticeContext(self.account, self.char1, session)
        with (
            patch("evennia_notices.services.connected_contexts", return_value=[context]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.emit(self.event("new"))
        session.msg.assert_called_once()
        self.assertIn("new", session.msg.call_args.args[0])
        self.assertNotIn("old", session.msg.call_args.args[0])

    def test_renderer_controls_are_removed_and_malformed_actions_defer(self):
        self.emit()
        with patch.object(
            Source, "render", return_value=RenderedNotice("safe\x1b[2J\x1b]0;title\x07text")
        ):
            self.assertEqual(project(self.context)[0].text, "safetext")
        with patch.object(
            Source, "render", return_value=RenderedNotice("safe", actions=(object(),))
        ):
            self.assertEqual(project(self.context), [])

    def test_projection_has_bounded_pages_and_opaque_cursor(self):
        for index in range(30):
            self.emit(self.event(str(index)))
        page = project(self.context)
        self.assertLessEqual(len(page), 25)
        following = project(self.context, cursor=page[-1].notice.public_ref)
        self.assertTrue(following)
        self.assertFalse({p.notice.pk for p in page} & {p.notice.pk for p in following})

    def test_fallback_continues_after_an_ineligible_session(self):
        from evennia_links.notices import default_fallback

        sessions = [Mock(), Mock()]
        contexts = [
            NoticeContext(self.account, character, session)
            for character, session in zip((self.char1, self.char2), sessions, strict=True)
        ]
        for context in contexts:
            context.session.get_account.return_value = self.account
            context.session.get_puppet.return_value = context.character

        def evaluate(events, context):
            return {
                e.event_id: Evaluation("hidden" if context.character == self.char1 else "visible")
                for e in events
            }

        with (
            patch("evennia_links.notices.connected_contexts", return_value=contexts),
            patch.object(Source, "evaluate", side_effect=evaluate),
        ):
            result = default_fallback(self.account, self.event(), None, Source())
        self.assertEqual(result.status, "delivered")
        sessions[1].msg.assert_called_once()
        sessions[0].msg.assert_not_called()

    def test_maintenance_disabled_never_creates_or_starts_script(self):
        from evennia_notices.scripts import ensure_notice_maintenance

        with (
            override_settings(NOTICES_ENABLED=False),
            patch("evennia.utils.create.create_script") as create,
        ):
            self.assertIsNone(ensure_notice_maintenance())
        create.assert_not_called()

    def test_maintenance_refuses_foreign_same_key_script(self):
        from evennia.utils.create import create_script

        from evennia_notices.scripts import ensure_notice_maintenance

        script = create_script("evennia.scripts.scripts.DefaultScript", key="notices-maintenance")
        with self.assertRaises(ValueError):
            ensure_notice_maintenance()
        self.assertTrue(type(script).objects.filter(pk=script.pk).exists())

    def test_distinct_social_senders_share_one_roster_scan_per_projection(self):
        from django.apps import apps

        if not apps.is_installed("evennia_social"):
            self.skipTest("Social physically absent")
        from evennia.utils.create import create_account, create_object

        from evennia_links import characters
        from evennia_social import ignore

        actors = []
        self.account.is_superuser = False
        self.account.permissions.clear()
        for index in range(6):
            account = create_account(f"Notice sender {index}", None, "fixture-password")
            character = create_object(
                type(self.char2), key=f"Notice actor {index}", location=self.room1
            )
            account.characters.add(character)
            ignore.set_entry(self.account, character)
            actors.append(character)
        self.account.is_superuser = True
        for index, actor in enumerate(actors):
            self.emit(self.event(str(index), actors=(ActorRef("character", actor.pk),)))
        self.account.is_superuser = False
        with patch.object(
            characters, "playable_accounts", wraps=characters.playable_accounts
        ) as scans:
            self.assertEqual(project(self.context), [])
        self.assertLessEqual(scans.call_count, 1)
        # No cache survives into a later operation or revives suppressed activity.
        with patch.object(
            characters, "playable_accounts", wraps=characters.playable_accounts
        ) as scans:
            self.assertEqual(project(self.context), [])
        self.assertEqual(scans.call_count, 1)

    def test_later_read_cannot_extend_retired_unread_history(self):
        self.emit(self.event("old", replacement_key="slot"))
        old_ref = Notice.objects.get().public_ref
        self.emit(self.event("new", replacement_key="slot"))
        Stored.objects.filter(event_id="old").update(inactive_at=self.now - timedelta(days=31))
        mutate(self.context, old_ref, "read")
        maintain(self.now)
        self.assertFalse(Stored.objects.filter(event_id="old").exists())
        self.assertEqual(DeliveryReceipt.objects.count(), 2)

    def test_shared_immediate_delivery_checks_each_sessions_preference(self):
        self.account2.characters.add(self.char1)
        set_preference(self.context, "test", "summary")
        second = NoticeContext(self.account2, self.char1)
        set_preference(second, "test", "immediate")
        sessions = [Mock(), Mock()]
        contexts = [
            NoticeContext(account, self.char1, session)
            for account, session in zip((self.account, self.account2), sessions, strict=True)
        ]
        for context in contexts:
            context.session.get_account.return_value = context.account
            context.session.get_puppet.return_value = self.char1
        with (
            patch("evennia_notices.services.connected_contexts", return_value=contexts),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self.emit(recipient=self.char1)
        self.assertEqual(result.status, "retained")
        sessions[0].msg.assert_not_called()
        sessions[1].msg.assert_called_once()

    def test_shared_creation_ignore_is_viewer_specific_and_durable(self):
        self.account2.characters.add(self.char1)

        def policy(viewer, **kwargs):
            return "hide" if viewer == self.account else None

        ignore_mode_requested.connect(policy, weak=False)
        try:
            result = self.emit(
                self.event(actors=(ActorRef("character", self.char2.pk),)), recipient=self.char1
            )
        finally:
            ignore_mode_requested.disconnect(policy)
        self.assertEqual(result.status, "retained")
        self.assertEqual(project(self.context), [])
        self.assertEqual(len(project(NoticeContext(self.account2, self.char1))), 1)
