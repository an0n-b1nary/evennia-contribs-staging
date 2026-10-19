# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Test runner that stops Evennia test tasks outliving their test.

Point a game's test settings at it::

    TEST_RUNNER = "evennia_links.testing.TestRunner"

Every ``EvenniaTest`` connects a dummy session in ``setUp``, and Evennia's
``portal_connect`` schedules the login command with ``utils.delay``. Under the
test mixin's mocked ``deferLater`` that task can never run: the mock calls
``TaskHandler.do_task`` before ``TaskHandler.add`` has stored the task's
deferred, ``do_task`` refuses a task without one, and ``add`` then stores a
``Deferred`` that never fires. The task stays in the process-wide
``TASK_HANDLER.tasks``, and its session keeps the test's accounts, characters,
rooms and their handlers alive. ``flush_cache()`` ends every test with a full
garbage collection, which walks that ever-growing heap, so a long serial run
slows down with every test it has already run.

This runner removes, at the end of each Evennia test, the tasks that test
added. A task scheduled in one test can never run in a later one, so no test
can observe the difference. It also prepares Django's parallel workers when
they are spawned instead of forked (the Linux default from Python 3.14), which
Evennia's own runner setup does not reach.

This works around Evennia 6.0's test harness; drop it once Evennia's
``EvenniaTestMixin`` cleans up its own login task.
"""

import functools

from django.test.runner import ParallelTestSuite
from evennia.server.tests.testrunner import EvenniaTestSuiteRunner

_ISOLATED = "_evennia_links_isolates_tasks"


def isolate_tasks():
    """Make ``EvenniaTestMixin`` remove the tasks each test schedules.

    Wraps the mixin's ``setUp`` to note the task ids that already exist and
    its ``tearDown`` to remove any others, before Evennia flushes its caches.
    Safe to call more than once. Django must be set up first.
    """
    from evennia.scripts.taskhandler import TASK_HANDLER
    from evennia.utils.test_resources import EvenniaTestMixin

    if getattr(EvenniaTestMixin.tearDown, _ISOLATED, False):
        return
    set_up, tear_down = EvenniaTestMixin.setUp, EvenniaTestMixin.tearDown

    @functools.wraps(set_up)
    def setUp(self):
        self._tasks_before_test = set(TASK_HANDLER.tasks)
        set_up(self)

    @functools.wraps(tear_down)
    def tearDown(self):
        before = getattr(self, "_tasks_before_test", None)
        if before is not None:
            for task_id in [task_id for task_id in TASK_HANDLER.tasks if task_id not in before]:
                TASK_HANDLER.remove(task_id)
        tear_down(self)

    setattr(tearDown, _ISOLATED, True)
    EvenniaTestMixin.setUp = setUp
    EvenniaTestMixin.tearDown = tearDown


def _prepare_worker(settings_module):
    """Set up a spawned or forkserver test worker the way the parent was.

    Django calls this before its own ``django.setup()``. Forked workers inherit
    the parent's state and never call it.

    Args:
        settings_module (str): The dotted settings module the parent loaded.
            ``evennia test --settings settings.py`` hands the bare filename on
            to Django, which writes it into ``DJANGO_SETTINGS_MODULE``; the
            parent has already loaded the right module by then, but a spawned
            worker would try to import ``settings.py`` as a module name.
    """
    import os

    import django

    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    django.setup()

    import evennia
    from django.conf import settings

    evennia._init()
    settings.TEST_ENVIRONMENT = True
    isolate_tasks()


class _ParallelTestSuite(ParallelTestSuite):
    process_setup = _prepare_worker

    def __init__(self, *args, **kwargs):
        from django.conf import settings

        super().__init__(*args, **kwargs)
        self.process_setup_args = (settings.SETTINGS_MODULE,)


class TestRunner(EvenniaTestSuiteRunner):
    """Evennia's test runner, with test tasks removed at the end of each test."""

    parallel_test_suite = _ParallelTestSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        isolate_tasks()
