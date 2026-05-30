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
