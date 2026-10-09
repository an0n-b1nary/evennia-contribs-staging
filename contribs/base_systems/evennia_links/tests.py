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
migrations directory, the probe tables are built by a ``post_migrate`` receiver
during test-database setup (see ``_create_probe_tables``) rather than by
``migrate`` itself.

EvenniaTest provides self.char1 / self.char2 (ObjectDB instances) and
self.room1, used here as generic linkable/versionable objects.
"""

from django.contrib.auth.models import AnonymousUser
from django.db import connection, models
from django.db.models.signals import post_migrate
from django.test import RequestFactory
from evennia.utils.test_resources import EvenniaTest

from evennia_links import (
    AbstractArchived,
    AbstractAuthoredLink,
    AbstractLink,
    AbstractVersion,
    collect_dicts,
    connect_on_ready,
    is_staff_user,
    resolve_dotted,
)


def runtime_probe_validator(value):
    return type(value) is int and value >= 0


class TestRuntimeControls(EvenniaTest):
    def setUp(self):
        super().setUp()
        from evennia_links import runtime

        runtime.register("LINKS_TEST_CONTROL", 7, validator=runtime_probe_validator)

    def tearDown(self):
        from evennia_links import runtime

        runtime._registry.pop("LINKS_TEST_CONTROL", None)
        super().tearDown()

    def test_override_host_default_precedence_and_reset(self):
        from evennia_links import runtime

        self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 7)
        with self.settings(LINKS_TEST_CONTROL=9):
            self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 9)
            runtime.set("LINKS_TEST_CONTROL", 11, by=self.char1)
            self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 11)
            runtime.reset("LINKS_TEST_CONTROL", by=self.char1)
            self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 9)

    def test_invalid_and_unregistered_controls_fail_closed(self):
        from evennia_links import runtime

        for name, value in (
            ("SECRET_KEY", 1),
            ("LINKS_TEST_CONTROL", -1),
            ("LINKS_TEST_CONTROL", True),
        ):
            with self.assertRaises(ValueError):
                runtime.set(name, value)
        with self.assertRaises(ValueError):
            runtime.get("SECRET_KEY")

    def test_reads_observe_external_writes_even_with_a_cached_config_instance(self):
        from evennia.server.models import ServerConfig
        from evennia.utils.dbserialize import to_pickle

        from evennia_links import runtime

        runtime.set("LINKS_TEST_CONTROL", 11)
        cached = ServerConfig.objects.get(db_key="runtime:LINKS_TEST_CONTROL")
        self.assertEqual(cached.value["value"], 11)
        ServerConfig.objects.filter(pk=cached.pk).update(db_value=to_pickle({"value": 15}))
        self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 15)

    def test_change_signal_runs_after_commit(self):
        from unittest.mock import Mock

        from evennia_links import runtime

        receiver = Mock(return_value=None)
        runtime.runtime_setting_changed.connect(receiver, weak=False)
        try:
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("LINKS_TEST_CONTROL", 12, by=self.char1)
                receiver.assert_not_called()
            self.assertEqual(receiver.call_args.kwargs["value"], 12)
            self.assertEqual(receiver.call_args.kwargs["by"], self.char1.pk)
        finally:
            runtime.runtime_setting_changed.disconnect(receiver)

    def test_rollback_keeps_value_and_suppresses_signal(self):
        from unittest.mock import Mock

        from django.db import transaction

        from evennia_links import runtime

        receiver = Mock(return_value=None)
        runtime.runtime_setting_changed.connect(receiver, weak=False)
        try:
            with (
                self.captureOnCommitCallbacks(execute=True),
                self.assertRaises(RuntimeError),
                transaction.atomic(),
            ):
                runtime.set("LINKS_TEST_CONTROL", 12)
                raise RuntimeError("Rollback")
            self.assertEqual(runtime.get("LINKS_TEST_CONTROL"), 7)
            receiver.assert_not_called()
        finally:
            runtime.runtime_setting_changed.disconnect(receiver)

    def test_provider_failure_and_invalid_raise_degrade_to_base(self):
        from evennia_links import runtime

        def invalid(**kwargs):
            return {
                "invalid": {"resources": -4},
                "fraction": {"resources": 1.5},
                "good": {"resources": 3},
            }

        runtime.cap_contributions.connect(invalid, weak=False)
        try:
            self.assertEqual(runtime.cap_raise(self.char1, "resources"), 3)
        finally:
            runtime.cap_contributions.disconnect(invalid)


class TestIsStaffUser(EvenniaTest):
    """The shared request-level staff policy fails closed and stays global."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_missing_and_anonymous_requests_are_not_staff(self):
        self.assertFalse(is_staff_user(None))
        self.assertFalse(is_staff_user(self._request(AnonymousUser())))

    def test_django_staff_flag_does_not_grant_access(self):
        from types import SimpleNamespace

        user = SimpleNamespace(
            is_authenticated=True,
            is_staff=True,
            locks=SimpleNamespace(check_lockstring=lambda *_: False),
        )
        self.assertFalse(is_staff_user(self._request(user)))

    def test_lock_exception_fails_closed_even_for_superuser(self):
        from types import SimpleNamespace

        def explode(*_args):
            raise RuntimeError("broken lock handler")

        user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=True,
            locks=SimpleNamespace(check_lockstring=explode),
        )
        self.assertFalse(is_staff_user(self._request(user)))

    def test_evennia_superuser_bypass_is_preserved(self):
        self.account.is_superuser = True
        self.assertTrue(is_staff_user(self._request(self.account)))

    def test_malformed_lock_cannot_grant_staff_access(self):
        self.account2.permissions.clear()
        self.assertFalse(is_staff_user(self._request(self.account2)))
        for lock in ("broken;cmd:all()", "cmd:all();broken;other:none()"):
            with self.subTest(lock=lock), self.settings(EVENNIA_WEB_STAFF_LOCK=lock):
                self.assertFalse(is_staff_user(self._request(self.account2)))

    def test_staff_lock_accepts_bare_and_prefixed_expressions(self):
        self.account2.permissions.add("Builder")
        for lock in ("perm(Builder)", "cmd:perm(Builder)"):
            with self.subTest(lock=lock), self.settings(EVENNIA_WEB_STAFF_LOCK=lock):
                self.assertTrue(is_staff_user(self._request(self.account2)))

    def test_settings_failure_does_not_fall_back_to_default_policy(self):
        from unittest.mock import PropertyMock, patch

        self.account.permissions.add("Builder")
        with patch("evennia_links.permissions.settings") as configured:
            configured.EVENNIA_WEB_STAFF_LOCK = "cmd:perm(Builder)"
            type(configured).EVENNIA_WEB_STAFF_PREDICATE = PropertyMock(
                side_effect=RuntimeError("unavailable settings")
            )
            self.assertFalse(is_staff_user(self._request(self.account)))

    def test_predicate_override_is_authoritative(self):
        from unittest.mock import patch

        with (
            self.settings(EVENNIA_WEB_STAFF_PREDICATE="tests.predicate"),
            patch(
                "evennia_links.permissions.resolve_dotted",
                return_value=lambda request: request.user is self.account,
            ),
        ):
            self.assertTrue(is_staff_user(self._request(self.account)))

    def test_broken_and_recursive_predicates_fail_closed(self):
        from unittest.mock import patch

        request = self._request(self.account)
        with (
            self.settings(EVENNIA_WEB_STAFF_PREDICATE="tests.broken"),
            patch(
                "evennia_links.permissions.resolve_dotted",
                side_effect=ImportError("missing"),
            ),
        ):
            self.assertFalse(is_staff_user(request))
        with (
            self.settings(EVENNIA_WEB_STAFF_PREDICATE="evennia_links.is_staff_user"),
            patch(
                "evennia_links.permissions.resolve_dotted",
                return_value=is_staff_user,
            ),
        ):
            self.assertFalse(is_staff_user(request))


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


PROBE_MODELS = (PlainLinkProbe, AuthoredLinkProbe, DocProbe, DocVersionProbe)


def _create_probe_tables(**kwargs):
    """Create any missing probe tables with the schema editor.

    Idempotent, and deliberately run outside any open transaction: SQLite's
    schema editor cannot toggle foreign-key checks inside one.
    """
    existing = connection.introspection.table_names()
    with connection.schema_editor() as schema_editor:
        for model in PROBE_MODELS:
            if model._meta.db_table not in existing:
                schema_editor.create_model(model)


# Build the probe tables during test-database setup, not on the first
# ProbeTablesTest.
#
# Once this module is imported the probe classes are registered in Django's
# app registry for the whole process, and they hold CASCADE foreign keys to
# ObjectDB — so *every* ObjectDB hard-delete from that point on, in any app's
# test suite sharing the process, makes Django's deletion collector query
# these tables. Creating them in ProbeTablesTest.setUpClass covers that only
# if a ProbeTablesTest happens to run first, which is purely an artifact of
# label order: `evennia test evennia_maps evennia_links` used to fail one
# unrelated maps test with
# ``sqlite3.OperationalError: no such table: evennia_links_plainlinkprobe``,
# while the reverse order passed. The test runner imports every test module
# (build_suite) before it creates the databases (setup_databases), so a
# post_migrate receiver connected here always fires, and always before any
# test runs. The tables are never dropped — empty throwaway tables in a test
# database are harmless; missing ones are not.
post_migrate.connect(_create_probe_tables, dispatch_uid="evennia_links.create_probe_tables")


class ProbeTablesTest(EvenniaTest):
    """Base test for cases that read or write the probe tables.

    The tables themselves come from the ``post_migrate`` receiver above; this
    class is the marker for "this case needs them", and re-checks them so a
    runner that somehow skipped ``post_migrate`` still gets a working suite.
    """

    probe_models = PROBE_MODELS

    @classmethod
    def setUpClass(cls):
        _create_probe_tables()
        super().setUpClass()


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
        link, _created = AuthoredLinkProbe.create_link(self.char1, self.char2)
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
# collect_dicts
# ---------------------------------------------------------------------------


class TestCollectDicts(EvenniaTest):
    def test_merges_dict_responses(self):
        from django.dispatch import Signal

        sig = Signal()

        def receiver_a(sender, **kw):
            return {"a": 1}

        def receiver_b(sender, **kw):
            return {"b": 2}

        sig.connect(receiver_a, dispatch_uid="test_a")
        sig.connect(receiver_b, dispatch_uid="test_b")
        try:
            merged = collect_dicts(sig, sender=None)
        finally:
            sig.disconnect(dispatch_uid="test_a")
            sig.disconnect(dispatch_uid="test_b")
        self.assertEqual(merged, {"a": 1, "b": 2})

    def test_no_receivers_returns_empty_dict(self):
        from django.dispatch import Signal

        sig = Signal()
        self.assertEqual(collect_dicts(sig, sender=None), {})

    def test_none_response_contributes_nothing(self):
        from django.dispatch import Signal

        sig = Signal()

        def receiver(sender, **kw):
            return None

        sig.connect(receiver, dispatch_uid="test_none")
        try:
            self.assertEqual(collect_dicts(sig, sender=None), {})
        finally:
            sig.disconnect(dispatch_uid="test_none")

    def test_raising_receiver_is_skipped_not_propagated(self):
        from django.dispatch import Signal

        sig = Signal()

        def bad_receiver(sender, **kw):
            raise RuntimeError("boom")

        def good_receiver(sender, **kw):
            return {"ok": True}

        sig.connect(bad_receiver, dispatch_uid="test_bad")
        sig.connect(good_receiver, dispatch_uid="test_good")
        try:
            merged = collect_dicts(sig, sender=None)
        finally:
            sig.disconnect(dispatch_uid="test_bad")
            sig.disconnect(dispatch_uid="test_good")
        self.assertEqual(merged, {"ok": True})

    def test_non_dict_response_is_skipped(self):
        from django.dispatch import Signal

        sig = Signal()

        def receiver(sender, **kw):
            return ["not", "a", "dict"]

        sig.connect(receiver, dispatch_uid="test_nondict")
        try:
            self.assertEqual(collect_dicts(sig, sender=None), {})
        finally:
            sig.disconnect(dispatch_uid="test_nondict")

    def test_key_collision_resolves_to_exactly_one_value(self):
        """Colliding keys must not crash or accumulate.

        Which provider wins is deliberately NOT asserted: receiver order is
        not part of the contract, and two providers claiming one key is a bug
        in the providers. All this guarantees is that the merge stays a flat
        dict with one value per key.
        """
        from django.dispatch import Signal

        sig = Signal()

        def receiver_1(sender, **kw):
            return {"key": "first"}

        def receiver_2(sender, **kw):
            return {"key": "second"}

        sig.connect(receiver_1, dispatch_uid="test_1")
        sig.connect(receiver_2, dispatch_uid="test_2")
        try:
            merged = collect_dicts(sig, sender=None)
        finally:
            sig.disconnect(dispatch_uid="test_1")
            sig.disconnect(dispatch_uid="test_2")
        self.assertEqual(list(merged), ["key"])
        self.assertIn(merged["key"], ("first", "second"))


# ---------------------------------------------------------------------------
# resolve_dotted
# ---------------------------------------------------------------------------


class TestResolveDotted(EvenniaTest):
    def test_none_input_returns_none(self):
        self.assertIsNone(resolve_dotted(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(resolve_dotted(""))

    def test_resolves_module_attribute(self):
        result = resolve_dotted("evennia_links.collect.collect_dicts")
        self.assertIs(result, collect_dicts)

    def test_bad_module_raises_import_error(self):
        with self.assertRaises(ImportError):
            resolve_dotted("nonexistent.module.path.attr")

    def test_dotless_path_raises_import_error(self):
        # The likeliest settings typo. Must not leak import_module's bare
        # ValueError("Empty module name") — callers guard on ImportError.
        with self.assertRaises(ImportError):
            resolve_dotted("notdotted")

    def test_bad_attribute_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            resolve_dotted("evennia_links.collect.not_a_real_attr")


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

        # Parent is char1. v1 is authored by char2; v2 is authored by char1.
        DocVersionProbe.create_version(self.char1, "by char2", editor=self.char2)
        DocVersionProbe.create_version(self.char1, "by char1", editor=self.char1)

        # Use a real ObjectDB character as caller so the editor FK filter runs against the DB.
        # char2 is non-staff, so view_versions should restrict to versions char2 authored (v1).
        caller = self.char2
        caller.msg = MagicMock()
        with patch.object(caller.locks, "check_lockstring", return_value=False):
            self._mixin(caller).view_versions(self.char1, DocVersionProbe, page=1)

        caller.msg.assert_called()
        output = caller.msg.call_args[0][0]
        # The editor FK filter must hide char1's version (v2) from non-staff char2.
        # Assert on version tokens, not editor_name — EvenniaTest's "Char"/"Char2" keys
        # are substrings of each other and would give a false pass.
        self.assertIn("v1", output)
        self.assertNotIn("v2", output)

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
