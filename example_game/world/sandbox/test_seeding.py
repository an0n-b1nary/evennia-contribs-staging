"""The class-seeded sandbox gives every test the same freshly seeded world."""

import unittest

from django.conf import settings
from evennia.utils.search import search_object
from evennia.utils.test_resources import EvenniaTest

from world.sandbox import content
from world.sandbox.seeding import SeededSandboxMixin, forget_cached_instances

ARRIVAL_HALL = content.OOC_ROOMS_BY_SLUG[content.ARRIVAL_SLUG].name


class TestSeededSandbox(SeededSandboxMixin, EvenniaTest):
    seeds = 0

    @classmethod
    def seed(cls):
        cls.seeds += 1
        super().seed()

    def test_the_class_seeds_once(self):
        self.assertEqual(type(self).seeds, 1)

    def test_room1_is_the_arrival_hall_and_char1_starts_there(self):
        self.assertEqual(self.room1.key, ARRIVAL_HALL)
        self.assertEqual(settings.START_LOCATION, f"#{self.room1.id}")
        self.assertEqual(self.char1.location, self.room1)
        self.assertEqual(self.exit.destination, self.room2)

    # Tests run in name order: "a" changes the world, "b" checks it was reset.
    def test_isolation_a_changes_the_seeded_world(self):
        self.room1.key = "Renamed hall"
        self.room1.db.visited = True
        self.room1.ndb.crowd = ["someone"]
        search_object("Proving Grounds")[0].delete()

    def test_isolation_b_sees_the_seeded_world_again(self):
        self.assertEqual(self.room1.key, ARRIVAL_HALL)
        self.assertIsNone(self.room1.db.visited)
        self.assertIsNone(self.room1.ndb.crowd)
        self.assertTrue(search_object("Proving Grounds"))


class TestSeededClassTimers(unittest.TestCase):
    """A plain TestCase, so the probe class's transaction is the outermost one."""

    # Running this class alone must still create the test database the probe uses.
    databases = frozenset({"default"})

    def new_loops(self, before):
        from twisted.internet import reactor
        from twisted.internet.task import LoopingCall

        loops = [
            call.func
            for call in reactor.getDelayedCalls()
            if call not in before and isinstance(call.func, LoopingCall)
        ]
        for loop in loops:
            self.addCleanup(lambda loop=loop: loop.running and loop.stop())
        return loops

    def assert_seeding_timers_stopped(self, loops, before):
        from twisted.internet import reactor

        # Seeding opens the Proving Grounds demo fight, which starts combat
        # maintenance as a timed script.
        self.assertTrue(loops)
        self.assertEqual([loop for loop in loops if loop.running], [])
        self.assertEqual(set(reactor.getDelayedCalls()) - before, set())

    def test_the_timers_seeding_starts_stop_when_the_class_ends(self):
        from twisted.internet import reactor

        before = set(reactor.getDelayedCalls())
        during = {}

        class Probe(SeededSandboxMixin, EvenniaTest):
            def test_probe(probe):
                during["loops"] = self.new_loops(before)

        result = unittest.TestResult()
        unittest.TestSuite([Probe("test_probe")]).run(result)

        self.assertEqual(result.errors + result.failures, [])
        self.assertEqual(result.testsRun, 1)
        self.assert_seeding_timers_stopped(during.get("loops", []), before)

    def test_the_timers_stop_when_seeding_fails(self):
        from twisted.internet import reactor

        before = set(reactor.getDelayedCalls())
        during = {}

        class Probe(SeededSandboxMixin, EvenniaTest):
            @classmethod
            def seed(cls):
                super().seed()
                during["loops"] = self.new_loops(before)
                raise RuntimeError("seeding failed after the fight opened")

            def test_probe(probe):
                pass

        # No probe test runs, so nothing else drops the seeded rows' cached instances.
        self.addCleanup(forget_cached_instances)
        result = unittest.TestResult()
        unittest.TestSuite([Probe("test_probe")]).run(result)

        self.assertEqual(result.testsRun, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("seeding failed after the fight opened", result.errors[0][1])
        self.assert_seeding_timers_stopped(during.get("loops", []), before)
