"""Evennia tests must not leave scheduled tasks behind when they finish."""

import unittest

from evennia.scripts.taskhandler import TASK_HANDLER
from evennia.utils.test_resources import EvenniaTest, EvenniaTestCase

from .testing import TestRunner, _prepare_worker, isolate_tasks


class TestTaskIsolation(EvenniaTestCase):
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
