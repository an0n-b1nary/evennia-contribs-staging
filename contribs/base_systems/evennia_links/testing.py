# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Test runner that stops Evennia tests' leftover work outliving them.

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
can observe the difference.

The same mixin creates its rooms, exit and characters with default locks that
their typeclasses then replace, and ``LockHandler`` reports each replacement
through ``logger.log_file``, which hands the write to the reactor's thread
pool. Tests never run the reactor or start that pool, so the writes queue
forever, five per test, each holding its ``Deferred`` and closures. The runner
stops the never-started pool, which makes it drop new work instead of queueing
it. That work could never run either way.

It also prepares Django's parallel workers when
they are spawned instead of forked (the Linux default from Python 3.14), which
Evennia's own runner setup does not reach.

This works around Evennia 6.0's test harness; drop it once Evennia's
``EvenniaTestMixin`` cleans up its own login task.
"""

import functools

from django.test.runner import ParallelTestSuite
from django.test.signals import setting_changed
from evennia.server.tests.testrunner import EvenniaTestSuiteRunner

_ISOLATED = "_evennia_links_isolates_tasks"


def _refresh_lock_functions(*, setting, **kwargs):
    """Restore host locks after stock-command tests temporarily replace settings."""
    if setting == "LOCK_FUNC_MODULES":
        from evennia.locks.lockhandler import _cache_lockfuncs

        _cache_lockfuncs()


def isolate_tasks():
    """Make ``EvenniaTestMixin`` remove the tasks each test schedules.

    Wraps the mixin's ``setUp`` to note the task ids that already exist and
    its ``tearDown`` to remove any others, before Evennia flushes its caches.
    Safe to call more than once. Django must be set up first.
    """
    from evennia.scripts.taskhandler import TASK_HANDLER
    from evennia.utils.test_resources import EvenniaTestMixin

    setting_changed.connect(
        _refresh_lock_functions, dispatch_uid="evennia_links.test_lock_functions", weak=False
    )
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


def discard_thread_work():
    """Stop the reactor's thread pool if it never started.

    A stopped pool drops new work, and the ``Deferred`` that ``deferToThread``
    returns never fires, as it never did while the work sat in the queue. The
    reactor's shutdown trigger is removed so it doesn't stop the pool again.
    Safe to call more than once. A started pool is left alone.
    """
    from twisted.internet import reactor

    pool = reactor.getThreadPool()
    if pool.started or pool.joined:
        return
    if reactor.threadpoolShutdownID is not None:
        reactor.removeSystemEventTrigger(reactor.threadpoolShutdownID)
        reactor.threadpoolShutdownID = None
    pool.stop()


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
    discard_thread_work()


class _ParallelTestSuite(ParallelTestSuite):
    process_setup = _prepare_worker

    def __init__(self, *args, **kwargs):
        from django.conf import settings

        super().__init__(*args, **kwargs)
        self.process_setup_args = (settings.SETTINGS_MODULE,)


class TestRunner(EvenniaTestSuiteRunner):
    """Evennia's test runner, with each test's leftover tasks and thread work dropped."""

    parallel_test_suite = _ParallelTestSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        isolate_tasks()
        discard_thread_work()


class EditorPersistenceMixin:
    """Exercise Evennia's real persisted editor format in contrib and host tests."""

    def reload_editor(self, caller, text="A draft that survives reload."):
        import pickle

        from evennia.utils.dbserialize import deserialize
        from evennia.utils.eveditor import _load_editor

        editor = caller.ndb._eveditor
        self.assertIsNotNone(editor, "The command did not open an editor")
        self.assertTrue(editor._persistent)
        editor.update_buffer(text)
        state = caller.attributes.get("_eveditor_saved")
        self.assertIsNotNone(state, "Editor fell back to non-persistent mode")
        self.assertTrue(state[0]["persistent"])
        pickle.loads(pickle.dumps(deserialize(state)))
        unsaved = caller.attributes.get("_eveditor_unsaved")
        caller.nattributes.clear()
        caller.attributes.reset_cache()
        _load_editor(caller)
        restored = caller.ndb._eveditor
        self.assertIsNot(restored, editor)
        self.assertEqual(restored._buffer, text)
        self.assertEqual(restored._unsaved, unsaved)
        return restored

    def save_and_quit_editor(self, caller, editor, context_key=None):
        editor.save_buffer()
        self.assertFalse(editor._unsaved, "The restored editor could not save its buffer")
        editor.quit()
        self.assertFalse(caller.attributes.has("_eveditor_saved"))
        if context_key:
            self.assertFalse(caller.attributes.has(context_key))
