"""The class-seeded sandbox gives every test the same freshly seeded world."""

from django.conf import settings
from evennia.utils.search import search_object
from evennia.utils.test_resources import EvenniaTest

from world.sandbox import content
from world.sandbox.seeding import SeededSandboxMixin

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
