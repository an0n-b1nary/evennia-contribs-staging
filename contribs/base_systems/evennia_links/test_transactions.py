"""SQL rollback must also restore objects already held by callers."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.db.backends.sqlite3.creation import DatabaseCreation
from django.test import SimpleTestCase, TransactionTestCase
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTest

from .transactions import atomic_objects


class TestAtomicObjects(EvenniaTest):
    def test_nested_rollback_restores_attributes_tags_locks_and_contents(self):
        self.room1.db.desc = "Original"
        original_locks = self.room1.db_lock_storage

        @atomic_objects
        def outer():
            self.room1.db.desc = "Outer change"

            @atomic_objects
            def inner():
                self.room1.db.desc = "Inner change"
                self.room1.tags.add("temporary")
                self.room1.locks.add("control:false()")
                self.obj1.location = self.room2
                create_object(
                    "evennia.objects.objects.DefaultExit",
                    key="Transient door",
                    location=self.room1,
                    destination=self.room2,
                )
                raise ValidationError("Reject inner transaction")

            with self.assertRaises(ValidationError):
                inner()
            self.assertEqual(self.room1.db.desc, "Outer change")
            self.assertEqual(self.obj1.location, self.room1)
            self.assertIn(self.obj1, self.room1.contents)
            self.assertNotIn(self.obj1, self.room2.contents)
            self.assertFalse(self.room1.tags.has("temporary"))
            self.assertEqual(self.room1.db_lock_storage, original_locks)
            self.assertFalse(ObjectDB.objects.filter(db_key="Transient door").exists())
            raise ValidationError("Reject outer transaction")

        with self.assertRaises(ValidationError):
            outer()
        self.assertEqual(self.room1.db.desc, "Original")

    def test_failed_cleanup_restores_deleted_objects_retained_by_caller(self):
        pk = self.obj1.pk

        @atomic_objects
        def cleanup():
            self.assertTrue(self.obj1.delete())
            raise ValidationError("Later cleanup failed")

        with self.assertRaises(ValidationError):
            cleanup()
        self.assertEqual(self.obj1.pk, pk)
        self.assertEqual(self.obj1.location, self.room1)
        self.assertIn(self.obj1, self.room1.contents)
        self.assertEqual(ObjectDB.objects.get(pk=pk), self.obj1)


FILE_BACKED_ONLY = (
    "Needs a file-backed test database: SQLite in memory fails competing writers at once"
)


def file_backed_test_db(alias=DEFAULT_DB_ALIAS):
    """Whether this run's test database for ``alias`` is a real database, not SQLite in memory.

    Read from settings, so it holds at import time and in every parallel worker.
    """
    db = connections[alias]
    if db.vendor != "sqlite":
        return True
    return not DatabaseCreation.is_in_memory_db(db.settings_dict["TEST"]["NAME"] or ":memory:")


def requires_file_backed_db(cls):
    """Class decorator: skip the whole class (no setUpClass, world or flush) on in-memory SQLite."""
    return skipUnless(file_backed_test_db(), FILE_BACKED_ONLY)(cls)


class TestFileBackedTestDB(SimpleTestCase):
    def test_test_name_decides(self):
        cases = [
            (None, False),
            ("", False),
            (":memory:", False),
            ("file:memorydb_default?mode=memory&cache=shared", False),
            ("/x/races.sqlite3", True),
            (Path("/x/races.sqlite3"), True),
        ]
        test_settings = connections["default"].settings_dict["TEST"]
        with patch.object(connections["default"], "vendor", "sqlite"):
            for name, expected in cases:
                with self.subTest(name=name), patch.dict(test_settings, NAME=name):
                    self.assertIs(file_backed_test_db(), expected)

    def test_other_vendors_run(self):
        test_settings = connections["default"].settings_dict["TEST"]
        with (
            patch.object(connections["default"], "vendor", "postgresql"),
            patch.dict(test_settings, NAME=None),
        ):
            self.assertIs(file_backed_test_db(), True)

    def test_agrees_with_this_runs_database(self):
        db = connections["default"]
        if db.vendor != "sqlite":
            self.assertIs(file_backed_test_db(), True)
            return
        self.assertEqual(file_backed_test_db(), not db.is_in_memory_db())

    def test_decorator_marks_the_class(self):
        test_settings = connections["default"].settings_dict["TEST"]
        with patch.object(connections["default"], "vendor", "sqlite"):
            with patch.dict(test_settings, NAME=None):
                skipped = requires_file_backed_db(type("Skipped", (TransactionTestCase,), {}))
            with patch.dict(test_settings, NAME="/x/races.sqlite3"):
                running = requires_file_backed_db(type("Running", (TransactionTestCase,), {}))
        self.assertTrue(skipped.__unittest_skip__)
        self.assertEqual(skipped.__unittest_skip_why__, FILE_BACKED_ONLY)
        self.assertFalse(getattr(running, "__unittest_skip__", False))


def committed_race(first, second):
    """Hold the first transaction until the second reaches its first SQL write."""
    ready, attempted, release = Event(), Event(), Event()

    def winner():
        connections.close_all()
        try:
            with transaction.atomic():
                result = first()
                ready.set()
                if not release.wait(20):
                    raise AssertionError("Competing writer did not start")
            return result
        finally:
            connections.close_all()

    def loser():
        connections.close_all()

        def notify(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("UPDATE"):
                attempted.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(notify):
                return second()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        winning = pool.submit(winner)
        if not ready.wait(20):
            release.set()
            winning.result(timeout=20)
            raise AssertionError("First transaction did not start")
        losing = pool.submit(loser)
        try:
            if not attempted.wait(20):
                raise AssertionError("Second transaction did not attempt a write")
        finally:
            release.set()
        winning.result(timeout=20)
        return losing.result(timeout=20)
