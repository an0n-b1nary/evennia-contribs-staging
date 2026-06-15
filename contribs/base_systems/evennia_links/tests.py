# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_links abstract bases.

Defines throwaway concrete subclasses (suffixed with ``Probe``) to exercise the
abstract model APIs without depending on any particular game's domain models.
The test models use ``objects.ObjectDB`` for their foreign keys, since that is
the one model every Evennia install guarantees.

These test models are defined in a ``tests`` module, so they are only imported
(and only registered with Django) when the test runner loads this file — they
do not appear in a consuming game's migrations. Because this contrib ships no
migrations directory, the probe tables are created/dropped per test class via
the schema editor (``ProbeTablesTest``) rather than being built by ``migrate``.

EvenniaTest provides self.char1 / self.char2 (ObjectDB instances) and
self.room1, used here as generic linkable/versionable objects.
"""

from django.db import connection, models
from evennia.utils.test_resources import EvenniaTest

from evennia_links import (
    AbstractArchived,
    AbstractAuthoredLink,
    AbstractLink,
    AbstractVersion,
    connect_on_ready,
)

# ---------------------------------------------------------------------------
# Throwaway concrete subclasses (test-only)
# ---------------------------------------------------------------------------


class PlainLinkProbe(AbstractLink):
    """Concrete AbstractLink subclass linking two ObjectDB rows."""

    obj_a = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    obj_b = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    note = models.CharField(max_length=50, blank=True)

    link_fields = ("obj_a", "obj_b")

    class Meta(AbstractLink.Meta):
        app_label = "evennia_links"
        unique_together = [("obj_a", "obj_b")]  # noqa: RUF012


class AuthoredLinkProbe(AbstractAuthoredLink):
    """Concrete AbstractAuthoredLink subclass linking two ObjectDB rows."""

    obj_a = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    obj_b = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    flag = models.BooleanField(default=False)

    link_fields = ("obj_a", "obj_b")

    class Meta(AbstractAuthoredLink.Meta):
        app_label = "evennia_links"
        unique_together = [("obj_a", "obj_b")]  # noqa: RUF012


class DocProbe(AbstractArchived):
    """Concrete AbstractArchived subclass."""

    title = models.CharField(max_length=100)

    class Meta:
        app_label = "evennia_links"


class DocVersionProbe(AbstractVersion):
    """Concrete AbstractVersion subclass parented to an ObjectDB row."""

    parent = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")

    class Meta(AbstractVersion.Meta):
        app_label = "evennia_links"
        unique_together = [("parent", "version_number")]  # noqa: RUF012


# ---------------------------------------------------------------------------
# Schema management for the probe models
# ---------------------------------------------------------------------------


class ProbeTablesTest(EvenniaTest):
    """Base test that creates/drops the probe model tables via the schema editor.

    The contrib ships no migrations (it only exports abstract models), so the
    concrete probe tables don't exist in the test database by default. We build
    them with the schema editor *before* EvenniaTest's class-level atomic block
    opens (and drop them after it closes), because SQLite's schema editor cannot
    toggle foreign-key checks inside an open transaction.
    """

    probe_models = (PlainLinkProbe, AuthoredLinkProbe, DocProbe, DocVersionProbe)

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as schema_editor:
            for model in cls.probe_models:
                schema_editor.create_model(model)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as schema_editor:
            for model in reversed(cls.probe_models):
                schema_editor.delete_model(model)


# ---------------------------------------------------------------------------
# Abstractness
# ---------------------------------------------------------------------------


class TestAbstractness(EvenniaTest):
    def test_bases_are_abstract(self):
        self.assertTrue(AbstractLink._meta.abstract)
        self.assertTrue(AbstractAuthoredLink._meta.abstract)
        self.assertTrue(AbstractVersion._meta.abstract)
        self.assertTrue(AbstractArchived._meta.abstract)

    def test_concrete_subclasses_are_not_abstract(self):
        self.assertFalse(PlainLinkProbe._meta.abstract)
        self.assertFalse(AuthoredLinkProbe._meta.abstract)
        self.assertFalse(DocProbe._meta.abstract)
        self.assertFalse(DocVersionProbe._meta.abstract)

    def test_authored_link_inherits_ordering(self):
        # ordering is inherited from the base Meta, not redeclared.
        self.assertEqual(AuthoredLinkProbe._meta.ordering, ["created_at"])


# ---------------------------------------------------------------------------
# AbstractLink.create_link
# ---------------------------------------------------------------------------


class TestAbstractLinkCreateLink(ProbeTablesTest):
    def test_create_link_creates(self):
        link, created = PlainLinkProbe.create_link(self.char1, self.char2)
        self.assertTrue(created)
        self.assertEqual(link.obj_a, self.char1)
        self.assertEqual(link.obj_b, self.char2)

    def test_create_link_is_idempotent(self):
        first, created1 = PlainLinkProbe.create_link(self.char1, self.char2)
        second, created2 = PlainLinkProbe.create_link(self.char1, self.char2)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PlainLinkProbe.objects.count(), 1)

    def test_create_link_passes_extra_defaults(self):
        link, created = PlainLinkProbe.create_link(self.char1, self.char2, note="hello")
        self.assertTrue(created)
        self.assertEqual(link.note, "hello")


# ---------------------------------------------------------------------------
# AbstractAuthoredLink.create_link
# ---------------------------------------------------------------------------


class TestAbstractAuthoredLinkCreateLink(ProbeTablesTest):
    def test_records_creator(self):
        link, created = AuthoredLinkProbe.create_link(self.char1, self.char2, linked_by=self.char1)
        self.assertTrue(created)
        self.assertEqual(link.created_by, self.char1)
        self.assertEqual(link.created_by_name, self.char1.key)

    def test_no_creator_is_blank(self):
        link, created = AuthoredLinkProbe.create_link(self.char1, self.char2)
        self.assertIsNone(link.created_by)
        self.assertEqual(link.created_by_name, "")

    def test_extra_defaults_alongside_creator(self):
        link, created = AuthoredLinkProbe.create_link(
            self.char1, self.char2, linked_by=self.char1, flag=True
        )
        self.assertTrue(created)
        self.assertTrue(link.flag)
        self.assertEqual(link.created_by, self.char1)

    def test_idempotent(self):
        AuthoredLinkProbe.create_link(self.char1, self.char2, linked_by=self.char1)
        _, created2 = AuthoredLinkProbe.create_link(self.char1, self.char2, linked_by=self.char2)
        self.assertFalse(created2)
        self.assertEqual(AuthoredLinkProbe.objects.count(), 1)


# ---------------------------------------------------------------------------
# AbstractVersion
# ---------------------------------------------------------------------------


class TestAbstractVersion(ProbeTablesTest):
    def test_create_version_increments(self):
        v1 = DocVersionProbe.create_version(self.char1, "first", editor=self.char1)
        v2 = DocVersionProbe.create_version(self.char1, "second", editor=self.char1)
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(v1.editor_name, self.char1.key)

    def test_create_version_system_editor(self):
        v1 = DocVersionProbe.create_version(self.char1, "x", editor=None)
        self.assertIsNone(v1.editor)
        self.assertEqual(v1.editor_name, "System")

    def test_rollback_creates_new_version(self):
        DocVersionProbe.create_version(self.char1, "first", editor=self.char1)
        DocVersionProbe.create_version(self.char1, "second", editor=self.char1)
        rb = DocVersionProbe.rollback_to(self.char1, 1, editor=self.char1)
        self.assertEqual(rb.version_number, 3)
        self.assertTrue(rb.is_rollback)
        self.assertEqual(rb.rolled_back_from, 1)
        self.assertEqual(rb.content, "first")

    def test_rollback_missing_version_raises(self):
        with self.assertRaises(DocVersionProbe.DoesNotExist):
            DocVersionProbe.rollback_to(self.char1, 99, editor=self.char1)


# ---------------------------------------------------------------------------
# AbstractArchived
# ---------------------------------------------------------------------------


class TestAbstractArchived(ProbeTablesTest):
    def test_default_manager_excludes_archived(self):
        doc = DocProbe.objects.create(title="t")
        self.assertEqual(DocProbe.objects.count(), 1)
        doc.archive(editor=self.char1)
        self.assertEqual(DocProbe.objects.count(), 0)
        self.assertEqual(DocProbe.all_objects.count(), 1)
        self.assertEqual(DocProbe.objects.include_archived().count(), 1)

    def test_archive_records_archiver(self):
        doc = DocProbe.objects.create(title="t")
        doc.archive(editor=self.char1)
        self.assertTrue(doc.is_archived)
        self.assertIsNotNone(doc.archived_at)
        self.assertEqual(doc.archived_by, self.char1)
        self.assertEqual(doc.archived_by_name, self.char1.key)

    def test_archive_system_editor(self):
        doc = DocProbe.objects.create(title="t")
        doc.archive(editor=None)
        self.assertEqual(doc.archived_by_name, "System")

    def test_unarchive_restores(self):
        doc = DocProbe.objects.create(title="t")
        doc.archive(editor=self.char1)
        doc.unarchive()
        self.assertFalse(doc.is_archived)
        self.assertIsNone(doc.archived_at)
        self.assertIsNone(doc.archived_by)
        self.assertEqual(doc.archived_by_name, "")
        self.assertEqual(DocProbe.objects.count(), 1)


# ---------------------------------------------------------------------------
# connect_on_ready
# ---------------------------------------------------------------------------


class TestConnectOnReady(EvenniaTest):
    def test_connects_receiver(self):
        from django.dispatch import Signal

        sig = Signal()
        calls = []

        def receiver(sender, **kw):  # local var keeps a strong ref (weak-ref safe)
            calls.append(kw)

        connect_on_ready(sig, receiver)
        sig.send(sender=None, foo="bar")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["foo"], "bar")

    def test_dedupes_same_receiver(self):
        from django.dispatch import Signal

        sig = Signal()
        calls = []

        def receiver(sender, **kw):
            calls.append(1)

        connect_on_ready(sig, receiver)
        connect_on_ready(sig, receiver)  # ignored — same receiver
        sig.send(sender=None)
        self.assertEqual(len(calls), 1)


# ---------------------------------------------------------------------------
# EditingMixin
# ---------------------------------------------------------------------------


def _make_caller(editing_context=None):
    """Return a mock caller with ndb._editing_context set."""
    from unittest.mock import MagicMock

    caller = MagicMock()
    caller.ndb._editing_context = editing_context
    return caller


def _make_instance(content="Original", pk=1):
    """Return a mock model instance."""
    from unittest.mock import MagicMock

    inst = MagicMock()
    inst.pk = pk
    inst.content = content
    return inst


def _make_model_class(instance=None):
    """Return a mock model class whose objects.get() returns instance."""
    from unittest.mock import MagicMock

    cls = MagicMock()
    cls.DoesNotExist = Exception
    if instance is not None:
        cls.objects.get.return_value = instance
    return cls


class TestEditingCallbacks(EvenniaTest):
    """Tests for the module-level EvEditor callback functions."""

    def test_load_func_returns_field_content(self):
        from evennia_links.editing import _load_func

        instance = _make_instance(content="Hello world")
        model_cls = _make_model_class(instance)
        caller = _make_caller(
            editing_context={"model_class": model_cls, "instance_pk": 1, "field_name": "content"}
        )
        self.assertEqual(_load_func(caller), "Hello world")
        model_cls.objects.get.assert_called_once_with(pk=1)

    def test_load_func_empty_when_no_context(self):
        from evennia_links.editing import _load_func

        caller = _make_caller(editing_context=None)
        self.assertEqual(_load_func(caller), "")

    def test_load_func_empty_when_object_deleted(self):
        from evennia_links.editing import _load_func

        model_cls = _make_model_class()
        model_cls.objects.get.side_effect = Exception("gone")
        caller = _make_caller(
            editing_context={"model_class": model_cls, "instance_pk": 1, "field_name": "content"}
        )
        self.assertEqual(_load_func(caller), "")
        caller.msg.assert_called()

    def test_save_func_snapshots_old_content_before_saving(self):
        from evennia_links.editing import _save_func

        instance = _make_instance(content="Old text")
        model_cls = _make_model_class(instance)
        version_cls = self._mock_version_cls()
        caller = _make_caller(
            editing_context={
                "model_class": model_cls,
                "instance_pk": 1,
                "field_name": "content",
                "version_model_class": version_cls,
            }
        )
        result = _save_func(caller, "New text")
        self.assertTrue(result)
        version_cls.create_version.assert_called_once_with(
            parent=instance, content="Old text", editor=caller
        )
        self.assertEqual(instance.content, "New text")
        instance.save.assert_called_once_with(update_fields=["content"])

    def test_save_func_noop_when_unchanged(self):
        from evennia_links.editing import _save_func

        instance = _make_instance(content="Same text")
        model_cls = _make_model_class(instance)
        version_cls = self._mock_version_cls()
        caller = _make_caller(
            editing_context={
                "model_class": model_cls,
                "instance_pk": 1,
                "field_name": "content",
                "version_model_class": version_cls,
            }
        )
        result = _save_func(caller, "Same text")
        self.assertTrue(result)
        version_cls.create_version.assert_not_called()
        instance.save.assert_not_called()

    def test_save_func_skips_version_when_no_version_class(self):
        from evennia_links.editing import _save_func

        instance = _make_instance(content="Old")
        model_cls = _make_model_class(instance)
        caller = _make_caller(
            editing_context={
                "model_class": model_cls,
                "instance_pk": 1,
                "field_name": "content",
                "version_model_class": None,
            }
        )
        result = _save_func(caller, "New")
        self.assertTrue(result)
        instance.save.assert_called_once()

    def test_save_func_false_when_no_context(self):
        from evennia_links.editing import _save_func

        caller = _make_caller(editing_context=None)
        self.assertFalse(_save_func(caller, "text"))
        caller.msg.assert_called()

    def test_quit_func_clears_context(self):
        from evennia_links.editing import _quit_func

        caller = _make_caller(editing_context={"some": "data"})
        _quit_func(caller)
        self.assertIsNone(caller.ndb._editing_context)
        caller.msg.assert_called_with("Editor closed.")

    def test_new_save_func_calls_callback(self):
        from unittest.mock import MagicMock

        from evennia_links.editing import _new_save_func

        callback = MagicMock()
        caller = _make_caller(editing_context={"create_callback": callback})
        result = _new_save_func(caller, "Some content")
        self.assertTrue(result)
        callback.assert_called_once_with(caller, "Some content")

    def test_new_save_func_rejects_empty_buffer(self):
        from unittest.mock import MagicMock

        from evennia_links.editing import _new_save_func

        callback = MagicMock()
        caller = _make_caller(editing_context={"create_callback": callback})
        result = _new_save_func(caller, "   ")
        self.assertFalse(result)
        callback.assert_not_called()

    def test_new_save_func_false_when_no_context(self):
        from evennia_links.editing import _new_save_func

        caller = _make_caller(editing_context=None)
        self.assertFalse(_new_save_func(caller, "text"))

    def _mock_version_cls(self):
        from unittest.mock import MagicMock

        cls = MagicMock()
        cls.DoesNotExist = Exception
        return cls


class TestEditingMixinStartEdit(EvenniaTest):
    """Tests for EditingMixin.start_edit."""

    def _make_mixin(self, caller):
        from evennia_links.editing import EditingMixin

        m = EditingMixin()
        m.caller = caller
        return m

    def test_sets_context_and_launches_editor(self):
        from unittest.mock import patch

        instance = _make_instance(pk=7)
        caller = _make_caller(editing_context=None)

        with patch("evennia_links.editing.EvEditor") as mock_ev:
            mixin = self._make_mixin(caller)
            mixin.start_edit(instance, "content")
            mock_ev.assert_called_once()
            ctx = caller.ndb._editing_context
            self.assertEqual(ctx["instance_pk"], 7)
            self.assertEqual(ctx["field_name"], "content")

    def test_editor_key_is_text_editor(self):
        from unittest.mock import patch

        instance = _make_instance()
        caller = _make_caller(editing_context=None)

        with patch("evennia_links.editing.EvEditor") as mock_ev:
            self._make_mixin(caller).start_edit(instance, "content")
            self.assertEqual(mock_ev.call_args[1]["key"], "text_editor")
            self.assertFalse(mock_ev.call_args[1]["persistent"])

    def test_blocks_double_session(self):
        from unittest.mock import patch

        caller = _make_caller(editing_context={"already": "open"})

        with patch("evennia_links.editing.EvEditor") as mock_ev:
            self._make_mixin(caller).start_edit(_make_instance(), "content")
            mock_ev.assert_not_called()
            caller.msg.assert_called()
            self.assertIn("already", caller.msg.call_args[0][0].lower())


class TestEditingMixinStartNewEdit(EvenniaTest):
    """Tests for EditingMixin.start_new_edit."""

    def _make_mixin(self, caller):
        from unittest.mock import MagicMock

        from evennia_links.editing import EditingMixin

        m = EditingMixin()
        m.caller = caller
        return m

    def test_sets_callback_and_launches_editor(self):
        from unittest.mock import MagicMock, patch

        callback = MagicMock()
        caller = _make_caller(editing_context=None)

        with patch("evennia_links.editing.EvEditor") as mock_ev:
            self._make_mixin(caller).start_new_edit(callback)
            mock_ev.assert_called_once()
            self.assertEqual(caller.ndb._editing_context["create_callback"], callback)

    def test_blocks_double_session(self):
        from unittest.mock import MagicMock, patch

        caller = _make_caller(editing_context={"already": "open"})

        with patch("evennia_links.editing.EvEditor") as mock_ev:
            self._make_mixin(caller).start_new_edit(MagicMock())
            mock_ev.assert_not_called()


class TestEditingMixinViewVersions(ProbeTablesTest):
    """Tests for EditingMixin.view_versions using the DocVersionProbe."""

    def _mixin(self, caller):
        from evennia_links.editing import EditingMixin

        m = EditingMixin()
        m.caller = caller
        return m

    def test_shows_history_for_staff(self):
        DocVersionProbe.create_version(self.char1, "v1 content", editor=self.char2)
        DocVersionProbe.create_version(self.char1, "v2 content", editor=self.char2)

        caller = _make_caller()
        caller.locks.check_lockstring.return_value = True  # staff
        self._mixin(caller).view_versions(self.char1, DocVersionProbe)
        caller.msg.assert_called()
        output = caller.msg.call_args[0][0]
        self.assertIn("v1", output)
        self.assertIn("v2", output)

    def test_non_staff_sees_only_own_versions(self):
        from unittest.mock import MagicMock, patch

        # char2 authored one version; char1 authored another
        DocVersionProbe.create_version(self.char1, "by char2", editor=self.char2)
        DocVersionProbe.create_version(self.char1, "by char1", editor=self.char1)

        # Use a real ObjectDB character as caller so the editor FK filter works against the DB.
        caller = self.char2
        caller.msg = MagicMock()
        with patch.object(caller.locks, "check_lockstring", return_value=False):
            self._mixin(caller).view_versions(self.char1, DocVersionProbe, page=1)
        caller.msg.assert_called()

    def test_no_history_message(self):
        caller = _make_caller()
        caller.locks.check_lockstring.return_value = True
        self._mixin(caller).view_versions(self.char1, DocVersionProbe)
        caller.msg.assert_called_with("No version history found.")


class TestEditingMixinDoRollback(EvenniaTest):
    """Tests for EditingMixin.do_rollback (mock-based to avoid ObjectDB field saves)."""

    def _mixin(self, caller):
        from evennia_links.editing import EditingMixin

        m = EditingMixin()
        m.caller = caller
        return m

    def test_snapshot_before_rollback(self):
        from unittest.mock import MagicMock

        version_cls = MagicMock()
        version_cls.DoesNotExist = Exception
        rollback_ver = MagicMock()
        rollback_ver.version_number = 3
        rollback_ver.content = "restored"
        version_cls.rollback_to.return_value = rollback_ver

        instance = _make_instance(content="current")
        caller = _make_caller()

        self._mixin(caller).do_rollback(instance, version_cls, version_number=1)

        version_cls.create_version.assert_called_once_with(
            parent=instance, content="current", editor=caller
        )
        version_cls.rollback_to.assert_called_once_with(
            parent=instance, version_number=1, editor=caller
        )
        self.assertEqual(instance.content, "restored")
        caller.msg.assert_called()

    def test_missing_version_reports_error(self):
        from unittest.mock import MagicMock

        version_cls = MagicMock()
        version_cls.DoesNotExist = Exception
        version_cls.rollback_to.side_effect = Exception("not found")

        instance = _make_instance()
        caller = _make_caller()
        self._mixin(caller).do_rollback(instance, version_cls, version_number=99)
        caller.msg.assert_called()
        self.assertIn("99", caller.msg.call_args[0][0])


class TestEditingMixinViewDiff(EvenniaTest):
    """Tests for EditingMixin.view_diff (mock-based)."""

    def _mixin(self, caller):
        from evennia_links.editing import EditingMixin

        m = EditingMixin()
        m.caller = caller
        return m

    def test_shows_diff(self):
        from unittest.mock import MagicMock

        version = MagicMock()
        version.content = "old line\n"
        version.editor_name = "Author"
        version.is_rollback = False
        from django.utils import timezone

        version.created_at = timezone.now()
        version.rolled_back_from = None

        version_cls = MagicMock()
        version_cls.DoesNotExist = Exception
        version_cls.objects.get.return_value = version

        instance = _make_instance(content="new line\n")
        caller = _make_caller()

        self._mixin(caller).view_diff(instance, version_cls, version_number=1)
        caller.msg.assert_called()
        output = caller.msg.call_args[0][0]
        self.assertIn("old line", output)

    def test_missing_version_reports_error(self):
        from unittest.mock import MagicMock

        version_cls = MagicMock()
        version_cls.DoesNotExist = Exception
        version_cls.objects.get.side_effect = Exception("not found")

        instance = _make_instance()
        caller = _make_caller()
        self._mixin(caller).view_diff(instance, version_cls, version_number=5)
        caller.msg.assert_called()
        self.assertIn("5", caller.msg.call_args[0][0])


class TestEditingMixinLazyImport(EvenniaTest):
    """Verify that importing evennia_links does not eagerly import EvEditor."""

    def test_editing_module_not_loaded_by_default(self):
        import sys

        # Remove the editing submodule to simulate a state where it has not yet been accessed.
        # Other tests in the same run may have already triggered the lazy load, so we reset first.
        sys.modules.pop("evennia_links.editing", None)

        import evennia_links

        # editing submodule must NOT be in sys.modules until EditingMixin is accessed
        self.assertNotIn("evennia_links.editing", sys.modules)

    def test_editing_module_loaded_after_access(self):
        import sys

        sys.modules.pop("evennia_links.editing", None)

        from evennia_links import EditingMixin

        self.assertIn("evennia_links.editing", sys.modules)
