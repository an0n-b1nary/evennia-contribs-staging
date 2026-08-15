# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_scenes contrib.

Uses EvenniaTest which provides:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.account, self.account2

This module doubles as a **test URLconf** (see ``urlpatterns`` below). Cases
that reverse a URL or render a template opt in with
``@override_settings(ROOT_URLCONF=__name__)``.

Run with:
    evennia test evennia_scenes --settings test_scenes_settings
"""

from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from evennia_scenes.capture import capture_to_scene, register_room_entry
from evennia_scenes.display import render_scene_ref
from evennia_scenes.models import LogEntry, LogEntryVersion, Scene, SceneParticipant
from evennia_scenes.views import (
    LogEntryDiffView,
    LogEntryEditView,
    LogEntryHistoryView,
    SceneDetailView,
    SceneListView,
)

# ---------------------------------------------------------------------------
# Test URLconf (see the module docstring)
# ---------------------------------------------------------------------------

# The scene templates reverse their own routes through the evennia_scenes
# namespace, so they are mounted namespaced exactly as urls.py documents.
# Evennia's own routes come along because website/base.html — which every
# scene template extends — reverses "index" and the account routes.
urlpatterns = [
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    *evennia_default_urlpatterns,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_scene(room, creator, title="Test Scene"):
    """Create and return a new open scene in room."""
    scene = Scene.objects.create(
        title=title,
        room=room,
        room_name=room.key,
        creator=creator,
        creator_name=creator.key,
    )
    room.active_scene_id = scene.pk
    return scene


def _add_participant(scene, character, *, is_active=True):
    participant, _ = SceneParticipant.objects.get_or_create(
        scene=scene,
        character=character,
        defaults={"character_name": character.key, "is_active": is_active},
    )
    return participant


# ---------------------------------------------------------------------------
# Scene model
# ---------------------------------------------------------------------------


class TestSceneModel(EvenniaTest):
    def test_create_defaults(self):
        scene = _open_scene(self.room1, self.char1)
        self.assertEqual(scene.creator, self.char1)
        self.assertEqual(scene.room, self.room1)
        self.assertEqual(scene.status, Scene.Status.OPEN)
        self.assertEqual(scene.privacy, Scene.Privacy.PUBLIC)
        self.assertIsNotNone(scene.created_at)
        self.assertIsNone(scene.started_at)
        self.assertIsNone(scene.ended_at)

    def test_str(self):
        scene = _open_scene(self.room1, self.char1, title="Rumble")
        self.assertIn("Rumble", str(scene))
        self.assertIn("Open", str(scene))

    def test_start_transitions_to_active(self):
        scene = _open_scene(self.room1, self.char1)
        scene.start()
        self.assertEqual(scene.status, Scene.Status.ACTIVE)
        self.assertIsNotNone(scene.started_at)

    def test_start_idempotent_when_already_active(self):
        scene = _open_scene(self.room1, self.char1)
        scene.start()
        started = scene.started_at
        scene.start()
        self.assertEqual(scene.started_at, started)

    def test_close_records_ended_at(self):
        scene = _open_scene(self.room1, self.char1)
        scene.start()
        scene.close()
        self.assertEqual(scene.status, Scene.Status.CLOSED)
        self.assertIsNotNone(scene.ended_at)

    def test_resume_clears_ended_at(self):
        scene = _open_scene(self.room1, self.char1)
        scene.start()
        scene.close()
        scene.resume()
        self.assertEqual(scene.status, Scene.Status.ACTIVE)
        self.assertIsNone(scene.ended_at)

    def test_close_noop_when_already_closed(self):
        scene = _open_scene(self.room1, self.char1)
        scene.start()
        scene.close()
        ended = scene.ended_at
        scene.close()
        self.assertEqual(scene.ended_at, ended)

    def test_all_objects_manager(self):
        scene = _open_scene(self.room1, self.char1)
        self.assertEqual(Scene.all_objects.filter(pk=scene.pk).count(), 1)

    def test_privacy_choices(self):
        scene = _open_scene(self.room1, self.char1)
        scene.privacy = Scene.Privacy.VIEW_PRIVATE
        scene.save(update_fields=["privacy"])
        scene.refresh_from_db()
        self.assertEqual(scene.privacy, Scene.Privacy.VIEW_PRIVATE)

    def test_title_optional(self):
        scene = _open_scene(self.room1, self.char1, title="")
        self.assertEqual(scene.title, "")


# ---------------------------------------------------------------------------
# SceneParticipant model
# ---------------------------------------------------------------------------


class TestSceneParticipantModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.scene = _open_scene(self.room1, self.char1)

    def test_create_participant(self):
        p = _add_participant(self.scene, self.char1)
        self.assertEqual(p.character, self.char1)
        self.assertEqual(p.character_name, self.char1.key)
        self.assertTrue(p.is_active)
        self.assertEqual(p.pose_count, 0)

    def test_leave_and_rejoin(self):
        p = _add_participant(self.scene, self.char1)
        p.leave()
        self.assertFalse(p.is_active)
        self.assertIsNotNone(p.left_at)
        p.rejoin()
        self.assertTrue(p.is_active)
        self.assertIsNone(p.left_at)

    def test_increment_pose_count(self):
        p = _add_participant(self.scene, self.char1)
        p.increment_pose_count()
        self.assertEqual(p.pose_count, 1)
        p.increment_pose_count()
        self.assertEqual(p.pose_count, 2)

    def test_unique_together_scene_character(self):
        from django.db import IntegrityError, transaction

        _add_participant(self.scene, self.char1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneParticipant.objects.create(
                scene=self.scene,
                character=self.char1,
                character_name=self.char1.key,
            )

    def test_str(self):
        p = _add_participant(self.scene, self.char1)
        self.assertIn(self.char1.key, str(p))
        self.assertIn("active", str(p))

    def test_str_after_leave(self):
        p = _add_participant(self.scene, self.char1)
        p.leave()
        self.assertIn("left", str(p))

    def test_is_invited_default_false(self):
        p = _add_participant(self.scene, self.char1)
        self.assertFalse(p.is_invited)


# ---------------------------------------------------------------------------
# LogEntry model
# ---------------------------------------------------------------------------


class TestLogEntryModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.scene = _open_scene(self.room1, self.char1)

    def test_create_entry_basic(self):
        entry = LogEntry.create_entry(
            scene=self.scene,
            author=self.char1,
            content="Hello world.",
        )
        self.assertEqual(entry.scene, self.scene)
        self.assertEqual(entry.author, self.char1)
        self.assertEqual(entry.author_name, self.char1.key)
        self.assertEqual(entry.content, "Hello world.")
        self.assertEqual(entry.log_type, LogEntry.LogType.POSE)
        self.assertFalse(entry.is_deleted)

    def test_create_entry_transitions_scene_to_active(self):
        self.assertEqual(self.scene.status, Scene.Status.OPEN)
        LogEntry.create_entry(scene=self.scene, author=self.char1, content="Pose.")
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.status, Scene.Status.ACTIVE)

    def test_system_entry_does_not_transition_scene(self):
        LogEntry.create_entry(
            scene=self.scene, author=None, content="System msg.", log_type="system"
        )
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.status, Scene.Status.OPEN)

    def test_auto_registers_participant(self):
        LogEntry.create_entry(scene=self.scene, author=self.char1, content="A pose.")
        self.assertTrue(
            SceneParticipant.objects.filter(scene=self.scene, character=self.char1).exists()
        )

    def test_increments_pose_count(self):
        LogEntry.create_entry(scene=self.scene, author=self.char1, content="Pose 1.")
        LogEntry.create_entry(scene=self.scene, author=self.char1, content="Pose 2.")
        p = SceneParticipant.objects.get(scene=self.scene, character=self.char1)
        self.assertEqual(p.pose_count, 2)

    def test_order_increments(self):
        e1 = LogEntry.create_entry(scene=self.scene, author=self.char1, content="A")
        e2 = LogEntry.create_entry(scene=self.scene, author=self.char1, content="B")
        self.assertEqual(e1.order, 1)
        self.assertEqual(e2.order, 2)

    def test_system_entry_author_name(self):
        entry = LogEntry.create_entry(
            scene=self.scene, author=None, content="System.", log_type="system"
        )
        self.assertEqual(entry.author_name, "System")
        self.assertIsNone(entry.author)

    def test_soft_delete(self):
        entry = LogEntry.create_entry(scene=self.scene, author=self.char1, content="X")
        entry.soft_delete()
        entry.refresh_from_db()
        self.assertTrue(entry.is_deleted)

    def test_log_entry_created_signal_fires(self):
        from evennia_scenes.signals import log_entry_created

        received = []

        def handler(sender, entry, scene, **kwargs):
            received.append((entry, scene))

        log_entry_created.connect(handler)
        try:
            LogEntry.create_entry(scene=self.scene, author=self.char1, content="Signal!")
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][1], self.scene)
        finally:
            log_entry_created.disconnect(handler)

    def test_str(self):
        entry = LogEntry.create_entry(scene=self.scene, author=self.char1, content="Foo.")
        self.assertIn("Pose", str(entry))
        self.assertIn(self.char1.key, str(entry))

    def test_web_ooc_does_not_register_participant(self):
        LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="OOC comment.", log_type="web_ooc"
        )
        self.assertFalse(
            SceneParticipant.objects.filter(scene=self.scene, character=self.char1).exists()
        )


# ---------------------------------------------------------------------------
# LogEntryVersion model
# ---------------------------------------------------------------------------


class TestLogEntryVersionModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.scene = _open_scene(self.room1, self.char1)
        self.entry = LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="Original content."
        )

    def test_create_version_increments(self):
        v1 = LogEntryVersion.create_version(
            parent=self.entry, content="Original content.", editor=self.char1
        )
        v2 = LogEntryVersion.create_version(
            parent=self.entry, content="After first edit.", editor=self.char1
        )
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)

    def test_rollback_creates_version(self):
        LogEntryVersion.create_version(
            parent=self.entry, content="Original content.", editor=self.char1
        )
        self.entry.content = "Edited content."
        self.entry.save()
        rollback_v = LogEntryVersion.rollback_to(
            parent=self.entry, version_number=1, editor=self.char2
        )
        self.assertTrue(rollback_v.is_rollback)
        self.assertEqual(rollback_v.rolled_back_from, 1)
        self.assertEqual(rollback_v.content, "Original content.")

    def test_editor_name_denormalised(self):
        v = LogEntryVersion.create_version(parent=self.entry, content="old", editor=self.char1)
        self.assertEqual(v.editor_name, self.char1.key)

    def test_unique_together_parent_version(self):
        from django.db import IntegrityError, transaction

        LogEntryVersion.create_version(parent=self.entry, content="v1", editor=self.char1)
        LogEntryVersion.objects.filter(parent=self.entry).update(version_number=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LogEntryVersion.objects.create(
                parent=self.entry,
                version_number=1,
                content="dup",
                editor=self.char1,
                editor_name=self.char1.key,
            )


# ---------------------------------------------------------------------------
# capture.py hooks
# ---------------------------------------------------------------------------


class TestCaptureHooks(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.scene = _open_scene(self.room1, self.char1)

    def test_capture_to_scene_creates_entry(self):
        capture_to_scene(self.char1, "A pose.", log_type="pose")
        self.assertEqual(self.scene.log_entries.count(), 1)
        entry = self.scene.log_entries.first()
        self.assertEqual(entry.author, self.char1)
        self.assertEqual(entry.content, "A pose.")

    def test_capture_to_scene_noop_no_location(self):
        self.char1.location = None
        capture_to_scene(self.char1, "Ghost pose.")
        self.assertEqual(self.scene.log_entries.count(), 0)

    def test_capture_to_scene_noop_no_active_scene(self):
        self.room1.active_scene_id = None
        capture_to_scene(self.char1, "Nothing.")
        self.assertEqual(self.scene.log_entries.count(), 0)

    def test_capture_to_scene_clears_stale_id(self):
        # Point room at a non-existent scene pk.
        self.room1.active_scene_id = 999999
        capture_to_scene(self.char1, "Stale.")
        self.assertIsNone(self.room1.active_scene_id)

    def test_register_room_entry_creates_participant(self):
        self.room1.active_scene_id = self.scene.pk
        register_room_entry(self.room1, self.char2)
        self.assertTrue(
            SceneParticipant.objects.filter(scene=self.scene, character=self.char2).exists()
        )

    def test_register_room_entry_rejoins_inactive(self):
        p = SceneParticipant.objects.create(
            scene=self.scene,
            character=self.char2,
            character_name=self.char2.key,
            is_active=False,
        )
        self.room1.active_scene_id = self.scene.pk
        register_room_entry(self.room1, self.char2)
        p.refresh_from_db()
        self.assertTrue(p.is_active)

    def test_register_room_entry_noop_no_active_scene(self):
        self.room1.active_scene_id = None
        register_room_entry(self.room1, self.char2)
        self.assertEqual(
            SceneParticipant.objects.filter(scene=self.scene, character=self.char2).count(), 0
        )

    def test_register_room_entry_clears_stale_id(self):
        self.room1.active_scene_id = 999999
        register_room_entry(self.room1, self.char2)
        self.assertIsNone(self.room1.active_scene_id)


# ---------------------------------------------------------------------------
# display.py
# ---------------------------------------------------------------------------


class TestRenderSceneRef(EvenniaTest):
    def test_renders_title(self):
        scene = _open_scene(self.room1, self.char1, title="Tavern Fight")
        result = render_scene_ref(scene.pk)
        self.assertIn(str(scene.pk), result)
        self.assertIn("Tavern Fight", result)

    def test_renders_untitled(self):
        scene = _open_scene(self.room1, self.char1, title="")
        result = render_scene_ref(scene.pk)
        self.assertIn("Untitled", result)

    def test_missing_pk_returns_fallback(self):
        result = render_scene_ref(999999)
        self.assertIn("999999", result)


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


class TestSignals(EvenniaTest):
    def test_scene_opened_fires(self):
        from evennia_scenes.signals import scene_opened

        received = []

        def handler(sender, scene, creator, **kwargs):
            received.append(scene)

        scene_opened.connect(handler)
        try:
            scene = _open_scene(self.room1, self.char1)
            scene_opened.send(sender=Scene, scene=scene, creator=self.char1)
            self.assertEqual(len(received), 1)
        finally:
            scene_opened.disconnect(handler)

    def test_scene_closed_fires(self):
        from evennia_scenes.signals import scene_closed

        received = []

        def handler(sender, scene, closer, **kwargs):
            received.append(scene)

        scene_closed.connect(handler)
        try:
            scene = _open_scene(self.room1, self.char1)
            scene.close()
            scene_closed.send(sender=Scene, scene=scene, closer=self.char1)
            self.assertEqual(len(received), 1)
        finally:
            scene_closed.disconnect(handler)


# ---------------------------------------------------------------------------
# commands — CmdScene
# ---------------------------------------------------------------------------


class TestCmdScene(EvenniaTest):
    def _call(self, cmd_str, caller=None):
        if caller is None:
            caller = self.char1
        from evennia_scenes.commands import CmdScene

        cmd = CmdScene()
        cmd.caller = caller
        raw_string = cmd_str
        # Parse /switch and args from the raw string after "+scene".
        cmd.raw_string = raw_string
        args_part = cmd_str[len("+scene") :].strip()
        if args_part.startswith("/"):
            switch_and_rest = args_part[1:].split(None, 1)
            cmd.switches = [switch_and_rest[0]]
            cmd.args = switch_and_rest[1] if len(switch_and_rest) > 1 else ""
        else:
            cmd.switches = []
            cmd.args = args_part
        cmd.lhs = cmd.args
        cmd.rhs = None
        return cmd

    def test_open_creates_scene(self):
        cmd = self._call("+scene/open Test Scene")
        cmd.func()
        self.assertEqual(Scene.objects.filter(room=self.room1).count(), 1)
        scene = Scene.objects.get(room=self.room1)
        self.assertEqual(scene.title, "Test Scene")
        self.assertEqual(scene.creator, self.char1)

    def test_open_creates_participant(self):
        cmd = self._call("+scene/open")
        cmd.func()
        scene = Scene.objects.get(room=self.room1)
        self.assertTrue(SceneParticipant.objects.filter(scene=scene, character=self.char1).exists())

    def test_open_prevents_double_open(self):
        cmd = self._call("+scene/open First")
        cmd.func()
        cmd2 = self._call("+scene/open Second")
        cmd2.func()
        # Still only one scene.
        self.assertEqual(Scene.objects.filter(room=self.room1).count(), 1)

    def test_close_sets_status(self):
        cmd = self._call("+scene/open Test")
        cmd.func()
        scene = Scene.objects.get(room=self.room1)
        cmd2 = self._call("+scene/close")
        cmd2.func()
        scene.refresh_from_db()
        self.assertEqual(scene.status, Scene.Status.CLOSED)

    def test_close_noop_when_no_active_scene(self):
        self.char1.msg = lambda *a, **kw: None  # swallow output
        cmd = self._call("+scene/close")
        cmd.func()

    def test_title_updates(self):
        cmd = self._call("+scene/open Draft")
        cmd.func()
        scene = Scene.objects.get(room=self.room1)
        cmd2 = self._call("+scene/title New Title")
        cmd2.func()
        scene.refresh_from_db()
        self.assertEqual(scene.title, "New Title")

    def test_info_shows_active_scene(self):
        cmd = self._call("+scene/open Backdrop")
        cmd.func()
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd2 = self._call("+scene/info")
        cmd2.func()
        self.assertTrue(any("Backdrop" in str(m) for m in msgs))

    def test_privacy_update(self):
        cmd = self._call("+scene/open Private Test")
        cmd.func()
        scene = Scene.objects.get(room=self.room1)
        cmd2 = self._call("+scene/privacy pose-private")
        cmd2.func()
        scene.refresh_from_db()
        self.assertEqual(scene.privacy, Scene.Privacy.POSE_PRIVATE)

    def test_show_status_no_scene(self):
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd = self._call("+scene")
        cmd.func()
        self.assertTrue(any("No active scene" in str(m) or "scene" in str(m).lower() for m in msgs))


# ---------------------------------------------------------------------------
# commands — _is_staff
# ---------------------------------------------------------------------------


class TestIsStaffHelper(EvenniaTest):
    def test_superuser_is_staff(self):
        from evennia_scenes.commands import _is_staff

        self.char1.account.is_superuser = True
        self.assertTrue(_is_staff(self.char1))

    def test_regular_character_returns_bool(self):
        from evennia_scenes.commands import _is_staff

        self.char1.account.is_superuser = False
        result = _is_staff(self.char1)
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# commands — CmdLog
# ---------------------------------------------------------------------------


class TestCmdLog(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.scene = _open_scene(self.room1, self.char1)
        self.entry = LogEntry.create_entry(scene=self.scene, author=self.char1, content="Original.")

    def _make_log_cmd(self, args="", switches=None, lhs="", rhs=None, caller=None):
        from evennia_scenes.commands import CmdLog

        cmd = CmdLog()
        cmd.caller = caller or self.char1
        cmd.args = args
        cmd.switches = switches or []
        cmd.lhs = lhs or args
        cmd.rhs = rhs
        return cmd

    def test_list_recent_no_participations(self):
        msgs = []
        self.char2.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(caller=self.char2)
        cmd.func()
        self.assertTrue(any("haven't participated" in str(m) for m in msgs))

    def test_view_log_shows_entries(self):
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(args=str(self.scene.pk), lhs=str(self.scene.pk))
        cmd.func()
        self.assertTrue(any("Original." in str(m) for m in msgs))

    def test_view_log_nonexistent_scene(self):
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(args="999999", lhs="999999")
        cmd.func()
        self.assertTrue(any("No scene found" in str(m) for m in msgs))

    def test_history_shows_versions(self):
        LogEntryVersion.create_version(parent=self.entry, content="Old.", editor=self.char1)
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(
            switches=["history"], args=str(self.entry.pk), lhs=str(self.entry.pk)
        )
        cmd.func()
        self.assertTrue(any("v1" in str(m) for m in msgs))

    def test_rollback_requires_staff(self):
        msgs = []
        self.char2.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(
            switches=["rollback"],
            lhs=str(self.entry.pk),
            rhs="1",
            caller=self.char2,
        )
        with patch.object(self.char2.locks, "check_lockstring", return_value=False):
            cmd.func()
        self.assertTrue(any("Only staff" in str(m) for m in msgs))

    def test_diff_missing_version_shows_versions(self):
        msgs = []
        self.char1.msg = lambda m, **kw: msgs.append(m)
        cmd = self._make_log_cmd(
            switches=["diff"],
            lhs=str(self.entry.pk),
            rhs="99",
        )
        cmd.func()
        # Should get some msg (error or version list) not an exception.
        self.assertIsNotNone(msgs)


# ---------------------------------------------------------------------------
# Web views — permission gate
# ---------------------------------------------------------------------------


class TestScenesAuthoringPermissionGate(EvenniaTest):
    """Authoring gate must deny before any DB write."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.scene = _open_scene(self.room1, self.char1)
        self.entry = LogEntry.create_entry(scene=self.scene, author=self.char1, content="Editable.")

    def test_anonymous_get_redirects_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        from evennia_scenes.views import LogEntryEditView

        req = self.factory.get("/")
        req.user = AnonymousUser()
        response = LogEntryEditView.as_view()(req, pk=self.scene.pk, entry_id=self.entry.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_no_puppet_raises_permission_denied(self):
        from django.core.exceptions import PermissionDenied

        from evennia_scenes.views import LogEntryEditView

        req = self.factory.get("/")
        req.user = self.account2  # no puppet in bare test context
        with self.assertRaises(PermissionDenied):
            LogEntryEditView.as_view()(req, pk=self.scene.pk, entry_id=self.entry.pk)

    def test_non_author_edit_denied_before_write(self):
        from django.core.exceptions import PermissionDenied

        from evennia_scenes.views import LogEntryEditView

        data = {"content": "Evil replacement."}
        with patch.object(self.account2, "get_all_puppets", return_value=[self.char2]):
            req = self.factory.post("/", data)
            req.user = self.account2  # char2 is not author of this entry
            with self.assertRaises(PermissionDenied):
                LogEntryEditView.as_view()(req, pk=self.scene.pk, entry_id=self.entry.pk)

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.content, "Editable.")
        self.assertEqual(LogEntryVersion.objects.filter(parent=self.entry).count(), 0)


# ---------------------------------------------------------------------------
# Web read views — render-checks + SceneDetailView parity
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF=__name__)
class TestWebPagesRender(EvenniaTest):
    """
    Render every scene page for real.

    This class used to only call get_template() on each file, on the reasoning
    that a contrib cannot full-render in isolation: the templates extend the
    host's website/base.html and reverse the host-wired evennia_scenes:
    namespace. That reasoning was wrong. Evennia ships website/base.html and
    its own urlpatterns, so a test module can mount this contrib's routes
    itself and splat Evennia's in after them — which is what urlpatterns above
    does. Compiling a template resolves no {% extends %} or {% include %}
    target and reverses no URL, so the old check could not have caught the
    NoReverseMatch and missing-partial faults that shipped in sibling contribs.

    RequestFactory + direct view invocation rather than Django's TestClient,
    because the TestClient trips an Evennia template-context RecursionError on
    authenticated HTML pages.
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.scene = _open_scene(self.room1, self.char1, title="Tavern Fight")
        _add_participant(self.scene, self.char1)
        self.entry = LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="An IC pose here.", log_type="pose"
        )
        self.scene.close(closer=self.char1)

    def _render(self, view, *, path_="/scenes/", user=None, puppet=None, **kwargs):
        request = self.factory.get(path_)
        request.user = AnonymousUser() if user is None else user
        # Evennia's general_context processor reads request.session["puppet"]
        # for any authenticated user, and RequestFactory attaches no session.
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        response.render()
        return response.content.decode()

    def _version(self, content="An older pose."):
        return LogEntryVersion.create_version(parent=self.entry, content=content, editor=self.char1)

    # -- scene archive ------------------------------------------------------

    def test_scene_list_renders_closed_scenes(self):
        html = self._render(SceneListView)
        self.assertIn("Scene Archive", html)
        self.assertIn("Tavern Fight", html)
        self.assertIn(f'href="/scenes/{self.scene.pk}/"', html)

    def test_scene_list_renders_its_empty_state(self):
        Scene.objects.all().delete()
        self.assertIn("No scenes have been archived yet.", self._render(SceneListView))

    # -- scene detail -------------------------------------------------------

    def test_scene_detail_renders_the_log_and_participants(self):
        html = self._render(SceneDetailView, path_=f"/scenes/{self.scene.pk}/", pk=self.scene.pk)
        self.assertIn("Tavern Fight", html)
        self.assertIn("An IC pose here.", html)
        self.assertIn(self.char1.key, html)

    def test_scene_detail_hides_ooc_from_the_rendered_log_by_default(self):
        LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="Some OOC chatter.", log_type="ooc"
        )
        html = self._render(SceneDetailView, path_=f"/scenes/{self.scene.pk}/", pk=self.scene.pk)
        self.assertNotIn("Some OOC chatter.", html)
        html = self._render(
            SceneDetailView,
            path_=f"/scenes/{self.scene.pk}/?include_ooc=1",
            pk=self.scene.pk,
        )
        self.assertIn("Some OOC chatter.", html)

    def test_scene_detail_offers_the_author_an_edit_link(self):
        html = self._render(
            SceneDetailView,
            path_=f"/scenes/{self.scene.pk}/",
            user=self.account,
            puppet=self.char1,
            pk=self.scene.pk,
        )
        self.assertIn(f"/scenes/{self.scene.pk}/log/{self.entry.pk}/edit/", html)

    def test_scene_detail_renders_an_empty_log(self):
        empty = _open_scene(self.room2, self.char1, title="Quiet Corner")
        empty.close(closer=self.char1)
        html = self._render(SceneDetailView, path_=f"/scenes/{empty.pk}/", pk=empty.pk)
        self.assertIn("No log entries found for this scene.", html)

    # -- log entry authoring / history --------------------------------------

    def test_log_edit_form_renders_with_the_existing_content(self):
        html = self._render(
            LogEntryEditView,
            path_=f"/scenes/{self.scene.pk}/log/{self.entry.pk}/edit/",
            user=self.account,
            puppet=self.char1,
            pk=self.scene.pk,
            entry_id=self.entry.pk,
        )
        self.assertIn(f"Edit Log Entry #{self.entry.pk}", html)
        self.assertIn("An IC pose here.", html)
        self.assertIn('name="csrfmiddlewaretoken"', html)

    def test_log_history_renders_versions(self):
        self._version()
        html = self._render(
            LogEntryHistoryView,
            path_=f"/scenes/{self.scene.pk}/log/{self.entry.pk}/history/",
            pk=self.scene.pk,
            entry_id=self.entry.pk,
        )
        self.assertIn("An older pose.", html)
        self.assertIn("An IC pose here.", html)

    def test_log_history_offers_diff_links_to_staff_only(self):
        version = self._version()
        diff_url = f"/scenes/{self.scene.pk}/log/{self.entry.pk}/diff/{version.version_number}/"
        history_path = f"/scenes/{self.scene.pk}/log/{self.entry.pk}/history/"
        anon = self._render(
            LogEntryHistoryView,
            path_=history_path,
            pk=self.scene.pk,
            entry_id=self.entry.pk,
        )
        self.assertNotIn(diff_url, anon)
        staff = self._render(
            LogEntryHistoryView,
            path_=history_path,
            user=self.account,
            puppet=self.char1,
            pk=self.scene.pk,
            entry_id=self.entry.pk,
        )
        self.assertIn(diff_url, staff)

    def test_log_history_renders_its_empty_state(self):
        html = self._render(
            LogEntryHistoryView,
            path_=f"/scenes/{self.scene.pk}/log/{self.entry.pk}/history/",
            pk=self.scene.pk,
            entry_id=self.entry.pk,
        )
        self.assertIn("No edit history found for this entry.", html)

    def test_log_diff_renders_both_sides(self):
        version = self._version()
        html = self._render(
            LogEntryDiffView,
            path_=f"/scenes/{self.scene.pk}/log/{self.entry.pk}/diff/{version.version_number}/",
            pk=self.scene.pk,
            entry_id=self.entry.pk,
            version_number=version.version_number,
        )
        self.assertIn("An older pose.", html)
        self.assertIn("An IC pose here.", html)

    def test_log_diff_reports_an_identical_version(self):
        version = self._version(content=self.entry.content)
        html = self._render(
            LogEntryDiffView,
            path_=f"/scenes/{self.scene.pk}/log/{self.entry.pk}/diff/{version.version_number}/",
            pk=self.scene.pk,
            entry_id=self.entry.pk,
            version_number=version.version_number,
        )
        self.assertIn("identical to the current content", html)


class TestSceneDetailViewVisibility(EvenniaTest):
    """SceneDetailView parity: only CLOSED, non-archived scenes are reachable,
    OOC is hidden by default, and VIEW_PRIVATE is gated. Assertions read
    response.context_data so they do not depend on the host base template /
    URLconf (no .render()).
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.scene = _open_scene(self.room1, self.char1)
        self.scene.status = Scene.Status.CLOSED
        self.scene.save()
        self.ic_entry = LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="An IC pose here.", log_type="pose"
        )
        self.ooc_entry = LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="Some OOC chatter.", log_type="ooc"
        )

    def _anon_get(self, path="/"):
        from django.contrib.auth.models import AnonymousUser

        req = self.factory.get(path)
        req.user = AnonymousUser()
        return req

    def test_detail_excludes_ooc_by_default(self):
        from evennia_scenes.views import SceneDetailView

        resp = SceneDetailView.as_view()(self._anon_get(), pk=self.scene.pk)
        entries = list(resp.context_data["log_entries"])
        self.assertIn(self.ic_entry, entries)
        self.assertNotIn(self.ooc_entry, entries)
        self.assertFalse(resp.context_data["include_ooc"])

    def test_detail_includes_ooc_with_param(self):
        from evennia_scenes.views import SceneDetailView

        resp = SceneDetailView.as_view()(self._anon_get("/?include_ooc=1"), pk=self.scene.pk)
        entries = list(resp.context_data["log_entries"])
        self.assertIn(self.ooc_entry, entries)
        self.assertTrue(resp.context_data["include_ooc"])

    def test_detail_open_scene_not_reachable(self):
        from django.http import Http404

        from evennia_scenes.views import SceneDetailView

        open_scene = _open_scene(self.room2, self.char1)  # status OPEN
        with self.assertRaises(Http404):
            SceneDetailView.as_view()(self._anon_get(), pk=open_scene.pk)

    def test_detail_archived_scene_not_reachable(self):
        from django.http import Http404

        from evennia_scenes.views import SceneDetailView

        self.scene.is_archived = True
        self.scene.save()
        with self.assertRaises(Http404):
            SceneDetailView.as_view()(self._anon_get(), pk=self.scene.pk)

    def test_detail_view_private_blocked_for_anon(self):
        from django.core.exceptions import PermissionDenied

        from evennia_scenes.views import SceneDetailView

        self.scene.privacy = Scene.Privacy.VIEW_PRIVATE
        self.scene.save()
        with self.assertRaises(PermissionDenied):
            SceneDetailView.as_view()(self._anon_get(), pk=self.scene.pk)


class TestWebReadableParityAcrossTiers(EvenniaTest):
    """Every consumer of Scene privacy answers "is this log public?" the same
    way, for every tier that exists.

    These used to be two encodings of one rule: SceneListView and the DRF
    SceneViewSet filtered ``privacy__in [PUBLIC, POSE_PRIVATE]`` while
    _can_view_scene() tested ``!= VIEW_PRIVATE``. Equivalent only while there
    are exactly three tiers — a game adding a fourth would have had it hidden
    from the listing but served by SceneDetailView and the history/diff
    drill-downs, which is the whole surface _can_view_scene() guards.

    Written as a loop over Scene.Privacy.choices rather than a case per tier,
    so a tier added downstream is covered the moment it is declared: it fails
    here unless it is classified in WEB_READABLE_PRIVACY and every consumer
    agrees about it.
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _anon_get(self):
        from django.contrib.auth.models import AnonymousUser

        req = self.factory.get("/")
        req.user = AnonymousUser()
        return req

    def test_listing_and_detail_agree_for_every_declared_tier(self):
        from django.core.exceptions import PermissionDenied

        from evennia_scenes.views import SceneDetailView, SceneListView

        for tier in Scene.Privacy.values:
            with self.subTest(tier=tier):
                scene = _open_scene(self.room1, self.char1)
                scene.status = Scene.Status.CLOSED
                scene.privacy = tier
                scene.save()
                expected = Scene.is_web_readable(tier)

                listed = SceneListView().get_queryset().filter(pk=scene.pk).exists()
                self.assertEqual(
                    listed, expected, f"SceneListView disagrees with is_web_readable() for {tier}"
                )

                if expected:
                    resp = SceneDetailView.as_view()(self._anon_get(), pk=scene.pk)
                    self.assertEqual(resp.status_code, 200)
                else:
                    with self.assertRaises(
                        PermissionDenied,
                        msg=f"detail view served a non-web-readable tier ({tier}) to anonymous",
                    ):
                        SceneDetailView.as_view()(self._anon_get(), pk=scene.pk)
                scene.delete()

    def test_api_queryset_agrees_for_every_declared_tier(self):
        # Requires the [web] extra; DRF's Request wrapper supplies the
        # .query_params SceneViewSet.get_queryset() reads.
        from rest_framework.request import Request

        from evennia_scenes.api.views import SceneViewSet

        for tier in Scene.Privacy.values:
            with self.subTest(tier=tier):
                scene = _open_scene(self.room1, self.char1)
                scene.status = Scene.Status.CLOSED
                scene.privacy = tier
                scene.save()

                viewset = SceneViewSet()
                viewset.request = Request(self.factory.get("/"))
                exposed = viewset.get_queryset().filter(pk=scene.pk).exists()
                self.assertEqual(
                    exposed,
                    Scene.is_web_readable(tier),
                    f"SceneViewSet disagrees with is_web_readable() for {tier}",
                )
                scene.delete()

    def test_web_readable_privacy_is_a_subset_of_declared_tiers(self):
        """A tier removed from Privacy must not linger in the readable set."""
        self.assertTrue(set(Scene.WEB_READABLE_PRIVACY).issubset(set(Scene.Privacy.values)))


class TestLogEntryDiffViewColorblindSafe(EvenniaTest):
    """The diff view must carry +/- text prefixes + CSS classes (not color alone)."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.scene = _open_scene(self.room1, self.char1)
        self.scene.status = Scene.Status.CLOSED
        self.scene.save()
        self.entry = LogEntry.create_entry(
            scene=self.scene, author=self.char1, content="Edited pose text."
        )
        LogEntryVersion.create_version(
            parent=self.entry, content="Original pose text.", editor=self.char1
        )

    def test_diff_lines_have_prefixes_and_classes(self):
        from django.contrib.auth.models import AnonymousUser

        from evennia_scenes.views import LogEntryDiffView

        req = self.factory.get("/")
        req.user = AnonymousUser()
        resp = LogEntryDiffView.as_view()(
            req, pk=self.scene.pk, entry_id=self.entry.pk, version_number=1
        )
        diff_lines = resp.context_data["diff_lines"]
        classes = {css for css, _line in diff_lines}
        self.assertIn("diff-add", classes)
        self.assertIn("diff-remove", classes)
        # Each add/remove line also carries a literal +/- text prefix.
        adds = [line for css, line in diff_lines if css == "diff-add"]
        removes = [line for css, line in diff_lines if css == "diff-remove"]
        self.assertTrue(all(line.startswith("+") for line in adds))
        self.assertTrue(all(line.startswith("-") for line in removes))


# ---------------------------------------------------------------------------
# __init__.py lazy exports
# ---------------------------------------------------------------------------


class TestLazyExports(EvenniaTest):
    def test_signal_exports_are_eager(self):
        import evennia_scenes

        self.assertTrue(hasattr(evennia_scenes, "scene_opened"))
        self.assertTrue(hasattr(evennia_scenes, "log_entry_created"))

    def test_scene_model_accessible(self):
        import evennia_scenes

        model = evennia_scenes.Scene
        self.assertIs(model, Scene)

    def test_status_enum_accessible(self):
        import evennia_scenes

        self.assertIs(evennia_scenes.Status, Scene.Status)

    def test_privacy_enum_accessible(self):
        import evennia_scenes

        self.assertIs(evennia_scenes.Privacy, Scene.Privacy)

    def test_role_enum_accessible(self):
        import evennia_scenes

        self.assertIs(evennia_scenes.Role, SceneParticipant.Role)

    def test_log_type_enum_accessible(self):
        import evennia_scenes

        self.assertIs(evennia_scenes.LogType, LogEntry.LogType)

    def test_dir_includes_lazy_names(self):
        import evennia_scenes

        names = dir(evennia_scenes)
        for name in ("Scene", "LogEntry", "Status", "Privacy"):
            self.assertIn(name, names)

    def test_unknown_attr_raises_attribute_error(self):
        import evennia_scenes

        with self.assertRaises(AttributeError):
            _ = evennia_scenes.DoesNotExist
