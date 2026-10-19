"""Test support: a seeded sandbox shared by every test in a class.

Lives outside the test modules so that test_rp_partners.py, which runs with
RP partners physically uninstalled, can use it without importing tests.py and
the partner seams it pulls in.
"""

from django.core.management import call_command
from django.test import override_settings


class SeededSandboxMixin:
    """Seed the sandbox once per test class, with room1 as the Arrival Hall.

    In a live game START_LOCATION is "#2" - Limbo, which `evennia migrate`
    creates and nothing deletes. That is the whole reason the seeder re-dresses
    that room rather than making a hall whose dbref would drift (see
    seed_sandbox.py::_spawn_room). Evennia's test fixtures never run
    initial_setup, so in a test database #2 is whichever object the fixture
    happened to create second - quite possibly a Character, which has no
    set_terrain().

    So the class makes a room to stand in for Limbo, points START_LOCATION at
    it and runs the real seeder once, inside the class's transaction. Each
    test's changes roll back to that seeded world. Seeding per test cost about
    four seconds a test and dominated the sandbox gate.

    Every test then gets the hall as room1: the rest of EvenniaTest's fixture
    (room2, the exit, objects, characters) is built inside it, so char1 stands
    in the Arrival Hall, which is what a real player sees on their first
    connect. Tests may still reseed; that runs against the same hall.

    The seeded rows keep their ids across tests, so every cached instance is
    dropped after each test: Evennia's own flush keeps objects that hold ndb
    data, and those would carry one test's in-memory state into the next.
    """

    @classmethod
    def setUpTestData(cls):
        from evennia.utils.create import create_object

        super().setUpTestData()
        hall = create_object(cls.room_typeclass, key="Room", nohome=True)
        cls.hall_id = hall.id
        with override_settings(START_LOCATION=f"#{hall.id}"):
            cls.seed()

    @classmethod
    def seed(cls):
        call_command("seed_sandbox", verbosity=0)

    def setUp(self):
        origin = self.settings(START_LOCATION=f"#{self.hall_id}")
        origin.enable()
        self.addCleanup(origin.disable)
        super().setUp()

    def create_rooms(self):
        from evennia.objects.models import ObjectDB
        from evennia.utils.create import create_object

        self.room1 = ObjectDB.objects.get_id(self.hall_id)
        self.room2 = create_object(self.room_typeclass, key="Room2")
        self.exit = create_object(
            self.exit_typeclass, key="out", location=self.room1, destination=self.room2
        )

    def tearDown(self):
        super().tearDown()
        forget_cached_instances()


def forget_cached_instances():
    """Drop every idmapper instance, including ones flush_cache() keeps.

    Walks the model classes the way flush_cache() does: only leaf classes, each
    of which reaches its concrete model's shared cache through __dbclass__.
    """
    from evennia.utils.idmapper.models import SharedMemoryModel

    models = [SharedMemoryModel]
    while models:
        model = models.pop()
        subclasses = model.__subclasses__()
        if subclasses:
            models.extend(subclasses)
        else:
            model.flush_instance_cache(force=True)
