"""Evennia tests must not leave scheduled tasks or thread work behind when they finish."""

import unittest
from unittest.mock import patch

from django.test import override_settings
from evennia.scripts.taskhandler import TASK_HANDLER
from evennia.utils.test_resources import EvenniaTest, EvenniaTestCase

from .testing import TestRunner, _prepare_worker, discard_thread_work, isolate_tasks


def syntax_test_lock(*args, **kwargs):
    return True


class TestTaskIsolation(EvenniaTestCase):
    def test_lock_function_cache_follows_temporary_test_settings(self):
        from evennia.locks import lockhandler

        isolate_tasks()
        with override_settings(LOCK_FUNC_MODULES=("evennia.locks.lockfuncs", __name__)):
            self.assertIn("syntax_test_lock", lockhandler._LOCKFUNCS)
            with override_settings(LOCK_FUNC_MODULES=("evennia.locks.lockfuncs",)):
                self.assertNotIn("syntax_test_lock", lockhandler._LOCKFUNCS)
            self.assertIn("syntax_test_lock", lockhandler._LOCKFUNCS)
        self.assertNotIn("syntax_test_lock", lockhandler._LOCKFUNCS)

    def run_evennia_test(self, body):
        class Probe(EvenniaTest):
            def test_probe(probe):
                body(probe)

        result = unittest.TestResult()
        Probe("test_probe")(result)
        self.assertEqual(result.errors + result.failures, [])

    def test_teardown_removes_the_login_task_and_its_session(self):
        isolate_tasks()
        before = set(TASK_HANDLER.tasks)
        during = {}

        def body(probe):
            during["tasks"] = {
                task_id: TASK_HANDLER.tasks[task_id]
                for task_id in TASK_HANDLER.tasks
                if task_id not in before
            }
            during["session"] = probe.session

        self.run_evennia_test(body)

        # Evennia 6.0 schedules a login task for the test session that never
        # runs. If this stops holding, the upstream fix has landed and
        # evennia_links.testing can go.
        held = [args for _, _, args, *_ in during["tasks"].values()]
        self.assertIn((during["session"],), [tuple(args) for args in held])
        self.assertEqual(set(TASK_HANDLER.tasks) - before, set())

    def test_tasks_from_before_the_test_survive_it(self):
        isolate_tasks()
        task = TASK_HANDLER.add(3600, print, "kept")
        self.addCleanup(TASK_HANDLER.remove, task.task_id)

        self.run_evennia_test(lambda probe: None)

        self.assertIn(task.task_id, TASK_HANDLER.tasks)

    def test_the_test_world_logs_lock_warnings_through_the_thread_pool(self):
        from evennia.locks.lockhandler import WARNING_LOG
        from evennia.utils import logger

        with patch.object(logger, "log_file", wraps=logger.log_file) as log_file:
            self.run_evennia_test(lambda probe: None)

        # Evennia 6.0 replaces default locks while creating the test world and
        # logs each replacement with log_file, which writes from the reactor's
        # thread pool. If this stops holding, discard_thread_work can go.
        warnings = [c for c in log_file.call_args_list if c.args[1:] == (WARNING_LOG,)]
        self.assertTrue(warnings)

    def test_thread_work_from_a_test_is_not_left_queued(self):
        from twisted.internet import reactor

        discard_thread_work()
        pool = reactor.getThreadPool()
        before = pool.q.qsize()

        self.run_evennia_test(lambda probe: None)

        self.assertFalse(pool.started)
        self.assertEqual(pool.q.qsize(), before)

    def test_discarding_thread_work_is_idempotent(self):
        discard_thread_work()
        discard_thread_work()

    def test_spawned_workers_get_the_settings_module_the_parent_loaded(self):
        from django.conf import settings

        suite = TestRunner.parallel_test_suite([], 2)
        self.assertIs(suite.process_setup.__func__, _prepare_worker)
        self.assertEqual(suite.process_setup_args, (settings.SETTINGS_MODULE,))

    def test_isolation_is_installed_once(self):
        isolate_tasks()
        from evennia.utils.test_resources import EvenniaTestMixin

        tear_down = EvenniaTestMixin.tearDown
        isolate_tasks()
        self.assertIs(EvenniaTestMixin.tearDown, tear_down)
