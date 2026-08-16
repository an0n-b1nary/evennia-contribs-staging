"""
Management command: seed_sandbox

Idempotent content-only reset: purges everything this command previously
created, then rebuilds a small default world touching every installed
contrib, so a fresh sandbox has populated data to test against immediately.

Does NOT touch accounts/characters — see scripts/reset_to_golden.sh for a
full wipe-to-default (accounts included).

Evennia objects (rooms, exits, plain objects) are purged by tag
("sandbox_default", category="sandbox") via search_tag, then recreated —
Evennia's batch processors are not idempotent on their own (see the
contrib-sandbox-server plan's note on batchprocessors.py), so this command
does the purge/rebuild itself rather than replaying a .ev/.py batch file.

Non-Evennia (plain Django) content — boards, posts, calendar events, lore
entries, plot threads/arcs, the region, the map plane, scenes — has no tag
mechanism, so it's purged by a fixed, recognizable name/title before
recreating.

The seeded world is deliberately *mappable*: the four original rooms plus two
more are linked by exits whose keys stay flavorful ("archive", "garden") but
which each carry a canonical direction as an alias, since evennia_maps'
layout only walks exits it can resolve to a direction (key **or** alias).
That is what lets this command place one origin tile and then let
layout.plan() derive the other five positions, rather than hardcoding six
coordinate pairs.

The seeded scenes/lore/event exist to light up all six tile overlays, so a
fresh sandbox can be hand-checked at /map/<pk>/ and /map/<pk>/live/ without
first creating content by hand.

One room is deliberately *not* created: the Sandbox Plaza. The settings that
name a spawn point (START_LOCATION, DEFAULT_HOME) have to hold dbrefs, because
Evennia resolves them with ObjectDB.objects.get_id(), which does not take
names. A Plaza created fresh on every run would move out from under them and
strand each new character. So the room already living at that dbref - Limbo,
made once by `evennia migrate` and never deleted - is re-dressed into the Plaza
instead, and left untagged so the purge cannot remove it. See _origin_room().

Usage:
    evennia seed_sandbox
    evennia seed_sandbox --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

SANDBOX_TAG = "sandbox_default"
SANDBOX_TAG_CATEGORY = "sandbox"

# Fixed names/titles used both to purge prior runs and to recreate content.
ROOM_NAMES = [
    "Sandbox Plaza",
    "The Archive",
    "Consulate Hall",
    "Staff Lounge",
    "Garden Walk",
    "The Overlook",
    "OOC Nexus",
]

# The OOC hub, resolved by evennia_social from settings.OOC_ROOM_DBREF by
# *name* (search_object matches names as well as dbrefs), which is what lets
# this command purge and recreate it without the setting going stale.
OOC_ROOM_NAME = "OOC Nexus"

# Rooms that take a map tile - everything but the OOC hub, which hangs off a
# direction-less flavor exit and so is never reached by layout.plan(). Tests
# count against this rather than ROOM_NAMES so "not every room is mapped"
# stays an asserted property instead of an off-by-one.
MAPPED_ROOM_NAMES = [n for n in ROOM_NAMES if n != OOC_ROOM_NAME]
BOARD_NAMES = ["General", "Cutscenes"]
LORE_TITLES = ["The Founding of the Sandbox", "Rumors from the Archive"]
PLOT_ARC_NAME = "Sandbox Genesis"
PLOT_THREAD_NAME = "The Founding Storm"
CALENDAR_EVENT_TITLE = "Sandbox Kickoff"
REGION_NAME = "The Commons"
PLANE_NAME = "Sandbox Overworld"
SCENE_TITLES = ["Kickoff Rehearsal", "A Quiet Hour in the Archive"]

# Terrain tags, resolved to a single tile terrain by MAPS_TERRAIN_PRECEDENCE
# (server/conf/settings.py). Set through Room.set_terrain() so the mixin fires
# terrain_changed and the tile snapshot follows.
ROOM_TERRAIN = {
    "Sandbox Plaza": {"urban"},
    "The Archive": {"urban"},
    "Consulate Hall": {"urban"},
    "Staff Lounge": {"urban"},
    "Garden Walk": {"forest"},
    "The Overlook": {"hills"},
}

# (from, to, (exit key, direction alias), (return key, return alias)).
# The direction alias is what makes the exit visible to evennia_maps' layout;
# the key is what a player types. Laid out as a plus around the Plaza with one
# room beyond the Archive, so the derived grid is not a trivial straight line.
ROOM_LINKS = [
    ("Sandbox Plaza", "The Archive", ("archive", "north"), ("plaza", "south")),
    ("Sandbox Plaza", "Consulate Hall", ("hall", "east"), ("plaza", "west")),
    ("Sandbox Plaza", "Staff Lounge", ("lounge", "south"), ("plaza", "north")),
    ("Sandbox Plaza", "Garden Walk", ("garden", "west"), ("plaza", "east")),
    ("The Archive", "The Overlook", ("overlook", "north"), ("archive", "south")),
]

# The room the map is anchored on: the one tile this command places by hand,
# from which layout.plan() derives the rest.
ORIGIN_ROOM_NAME = "Sandbox Plaza"

# Exits carrying no direction alias. layout.plan() walks only exits it can
# resolve to a canonical direction, so these deliberately do *not* extend the
# map - which is why the OOC Nexus, reachable only through one of them, never
# takes a tile. It doubles as the honest demo of the thing players trip on:
# `@dig north=X` grows the map, `@dig gate=X` does not.
# (from, to, exit key, return key)
FLAVOR_LINKS = [
    (ORIGIN_ROOM_NAME, OOC_ROOM_NAME, "nexus", "plaza"),
]


class Command(BaseCommand):
    help = "Idempotent content-only reset: purge + rebuild the sandbox's default world."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would be purged/created without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # Django passes verbosity to every management command; honouring it
        # keeps world/sandbox/tests.py (which runs this command for real,
        # once per test) from burying the test output in seed reports.
        self.quiet = options.get("verbosity", 1) == 0
        mode = "DRY RUN" if dry_run else "LIVE"
        self._say(self.style.NOTICE(f"seed_sandbox [{mode}]"))

        purged = self._purge(dry_run)
        self._say(f"Purged: {purged}")

        if dry_run:
            self._say(self.style.WARNING("[DRY RUN] Skipping rebuild."))
            return

        created = self._rebuild()
        self._say(self.style.SUCCESS(f"Created: {created}"))

    def _say(self, message):
        if not self.quiet:
            self.stdout.write(message)

    # ------------------------------------------------------------------
    # Purge
    # ------------------------------------------------------------------

    def _purge(self, dry_run):
        from evennia.utils.search import search_tag

        counts = {}

        objs = search_tag(SANDBOX_TAG, category=SANDBOX_TAG_CATEGORY)
        counts["evennia_objects"] = len(objs)
        if not dry_run:
            # Deleting a room cascades to its contents (exits, plain
            # objects). Evennia doesn't null out an already-deleted
            # instance's pk — it monkey-patches .delete() to raise
            # ObjectDoesNotExist instead — so tolerate that rather than
            # trying to detect it beforehand.
            import contextlib

            from django.core.exceptions import ObjectDoesNotExist
            from evennia.objects.objects import DefaultRoom

            non_rooms = [obj for obj in objs if not obj.is_typeclass(DefaultRoom, exact=False)]
            rooms = [obj for obj in objs if obj.is_typeclass(DefaultRoom, exact=False)]
            for obj in non_rooms + rooms:
                with contextlib.suppress(ObjectDoesNotExist):
                    obj.delete()

        from evennia_boards.models import Board

        boards = Board.objects.filter(name__in=BOARD_NAMES)
        counts["boards"] = boards.count()
        if not dry_run:
            boards.delete()  # cascades to Post/PostVersion

        from evennia_calendar.models import CalendarEvent

        events = CalendarEvent.objects.filter(title=CALENDAR_EVENT_TITLE)
        counts["calendar_events"] = events.count()
        if not dry_run:
            events.delete()

        from evennia_lore.models import LoreEntry

        entries = LoreEntry.all_objects.filter(title__in=LORE_TITLES)
        counts["lore_entries"] = entries.count()
        if not dry_run:
            entries.delete()

        from evennia_plots.models import PlotArc, PlotThread

        threads = PlotThread.objects.filter(name=PLOT_THREAD_NAME)
        counts["plot_threads"] = threads.count()
        if not dry_run:
            threads.delete()

        arcs = PlotArc.objects.filter(name=PLOT_ARC_NAME)
        counts["plot_arcs"] = arcs.count()
        if not dry_run:
            arcs.delete()

        # all_objects (not objects): both models are AbstractArchived, whose
        # default manager hides archived rows — a previously-archived seed
        # region or plane would otherwise survive the purge and then collide
        # with the rebuild's unique name.
        from evennia_regions.models import Region

        regions = Region.all_objects.filter(name=REGION_NAME)
        counts["regions"] = regions.count()
        if not dry_run:
            regions.delete()  # cascades to RegionMembership

        from evennia_maps.models import MapPlane

        planes = MapPlane.all_objects.filter(name=PLANE_NAME)
        counts["map_planes"] = planes.count()
        if not dry_run:
            planes.delete()  # cascades to RoomTile

        from evennia_scenes.models import Scene

        scenes = Scene.all_objects.filter(title__in=SCENE_TITLES)
        counts["scenes"] = scenes.count()
        if not dry_run:
            scenes.delete()

        return counts

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self):
        counts = {}
        rooms = self._create_rooms()
        counts["rooms"] = len(rooms)
        counts["exits"] = self._create_exits(rooms)
        counts["objects"] = self._create_objects(rooms)
        counts["boards"] = self._create_boards()
        event = self._create_calendar_event()
        counts["calendar_events"] = 1
        entries = self._create_lore()
        counts["lore_entries"] = len(entries)
        counts["plot_arcs"], counts["plot_threads"] = self._create_plot()

        # Regions and maps come after the rooms and exits they describe, and
        # before the scenes/links that light the tile overlays.
        region = self._create_region(rooms)
        counts["region_memberships"] = region.member_count()
        counts["map_tiles"] = self._create_map(rooms)
        scenes, live_scene = self._create_scenes(rooms)
        counts["scenes"] = scenes
        counts["overlay_links"] = self._link_overlays(region, entries, event, live_scene)
        return counts

    def _tag(self, obj):
        obj.tags.add(SANDBOX_TAG, category=SANDBOX_TAG_CATEGORY)

    def _origin_room(self):
        """Return the permanent room settings.START_LOCATION points at.

        This is the one room the seeder re-dresses rather than creates, and the
        reason is that START_LOCATION/DEFAULT_HOME must be dbrefs: Evennia
        resolves them with ObjectDB.objects.get_id(), which does not accept
        names. A Plaza created fresh each run would take a new dbref every time
        and leave those settings pointing at a deleted room, so every new
        character would spawn nowhere.

        Limbo (#2) is created once by `evennia migrate` and never deleted, so it
        is the only dbref stable across both a reseed and a golden-DB restore.
        The room is left deliberately untagged so _purge() cannot remove it.
        """
        from django.conf import settings
        from evennia.objects.models import ObjectDB

        dbref = getattr(settings, "START_LOCATION", None)
        room = ObjectDB.objects.get_id(dbref) if dbref else None
        if room is None:
            raise CommandError(
                f"settings.START_LOCATION ({dbref!r}) resolves to no object. It must be "
                "the dbref of an existing room - normally '#2', Limbo."
            )
        return room

    def _create_rooms(self):
        from evennia.utils import create

        rooms = {}
        for name in ROOM_NAMES:
            if name == ORIGIN_ROOM_NAME:
                room = self._origin_room()
                room.key = name
                # Reset rather than assume: this room survives every purge, so
                # anything a builder changed on it last session is still here.
                room.room_type = "ic"
            else:
                room = create.create_object(
                    "typeclasses.rooms.Room",
                    key=name,
                )
                self._tag(room)
            room.db.desc = f"{name}. Default sandbox content — safe to explore and pose in."
            if name in ("Staff Lounge", OOC_ROOM_NAME):
                room.room_type = "ooc"
            # MapsRoomMixin (typeclasses/rooms.py). set_terrain() rather than
            # assigning terrain_tags, so terrain_changed fires and any tile
            # already placed for this room refreshes its snapshot. Here the
            # tiles do not exist yet, so it is place_tile() that reads these
            # — the call still goes through the mixin so the seeded world
            # matches what a builder typing the same thing would produce.
            terrain = ROOM_TERRAIN.get(name)
            if terrain or name == ORIGIN_ROOM_NAME:
                # set_terrain() replaces, so calling it unconditionally for the
                # surviving origin room clears last run's terrain instead of
                # letting it accumulate.
                room.set_terrain(terrain)
            rooms[name] = room
        return rooms

    def _create_exits(self, rooms):
        from evennia.utils import create

        # A plus-shaped layout around the Plaza, each link bidirectional.
        # Every exit carries a canonical direction as an alias (see
        # ROOM_LINKS): evennia_maps' layout walks only exits it can resolve
        # to a direction, and it matches the key *or* any alias — so "go
        # archive" still works while the map still knows the Archive is
        # north. Exits are created before any tile exists, so the
        # auto-placement listener (evennia_maps.listeners) deliberately
        # no-ops here; _create_map() derives the whole grid in one pass
        # instead.
        count = 0
        for a_name, b_name, (a_key, a_dir), (b_key, b_dir) in ROOM_LINKS:
            a, b = rooms[a_name], rooms[b_name]
            exit_a = create.create_object(
                "typeclasses.exits.Exit",
                key=a_key,
                aliases=[a_dir],
                location=a,
                destination=b,
            )
            self._tag(exit_a)
            exit_b = create.create_object(
                "typeclasses.exits.Exit",
                key=b_key,
                aliases=[b_dir],
                location=b,
                destination=a,
            )
            self._tag(exit_b)
            count += 2

        for a_name, b_name, a_key, b_key in FLAVOR_LINKS:
            a, b = rooms[a_name], rooms[b_name]
            for source, destination, key in ((a, b, a_key), (b, a, b_key)):
                flavor_exit = create.create_object(
                    "typeclasses.exits.Exit",
                    key=key,
                    location=source,
                    destination=destination,
                )
                self._tag(flavor_exit)
                count += 1
        return count

    def _create_objects(self, rooms):
        from evennia.utils import create

        plaque = create.create_object(
            "typeclasses.objects.Object",
            key="brass plaque",
            location=rooms["Sandbox Plaza"],
        )
        plaque.db.desc = (
            "A brass plaque reads: 'This sandbox resets to default content via "
            "`evennia seed_sandbox`. Golden full-reset: scripts/reset_to_golden.sh.'"
        )
        self._tag(plaque)
        return 1

    def _create_boards(self):
        # Django-model content (boards/posts and the calendar/lore/plot rows
        # below) has no Evennia tag handler, so it's purged by name/title in
        # _purge() rather than by the sandbox_default tag.
        from evennia_boards.models import Board

        Board.objects.create(
            name="General",
            description="OOC discussion.",
            board_type=Board.BoardType.OOC,
            order=0,
        )
        cutscenes = Board.objects.create(
            name="Cutscenes",
            description="In-character narrative posts.",
            board_type=Board.BoardType.IC,
            order=1,
        )

        from evennia_boards.models import Post

        Post.create_post(
            board=cutscenes,
            author=None,
            title="Welcome to the Sandbox",
            content=(
                "This is a seeded cutscene post on an IC board — pose here to "
                "generate XP-eligible content once evennia-xp's weekly batch runs."
            ),
        )
        return 2

    def _create_calendar_event(self):
        from datetime import UTC, datetime, timedelta

        from evennia_calendar.models import CalendarEvent

        # Returned (not counted) because _link_overlays() attaches it to a
        # scene: that link is the only path an event has to a room, and so the
        # only way it reaches the map's upcoming_events overlay.
        return CalendarEvent.create_event(
            creator=None,
            title=CALENDAR_EVENT_TITLE,
            scheduled_time=datetime.now(UTC) + timedelta(days=7),
            description="A seeded open event — RSVP with +rsvp.",
            emphasis=CalendarEvent.Emphasis.FREEFORM,
        )

    def _create_lore(self):
        from evennia_lore.models import LoreEntry

        # Returned so _link_overlays() can attach these to the region — lore
        # hangs off regions, never off rooms, which is why the has_lore overlay
        # resolves each room's primary region before it can answer.
        return [
            LoreEntry.create_entry(
                title=LORE_TITLES[0],
                author=None,
                body="In the beginning, a handful of rooms and a brass plaque...",
                privacy=LoreEntry.Privacy.PUBLIC,
            ),
            LoreEntry.create_entry(
                title=LORE_TITLES[1],
                author=None,
                body="Some say the Archive holds every seed this sandbox has ever grown.",
                privacy=LoreEntry.Privacy.PUBLIC,
            ),
        ]

    def _create_plot(self):
        from django.db.models import Max
        from evennia_plots.models import PlotArc, PlotThread

        # PlotArc has no create classmethod, so assign arc_number ourselves.
        # Compute max+1 (rather than hardcoding 1) and only claim is_current
        # when no other arc already holds it — otherwise seeding on a DB where
        # staff already ran +arc would hit the unique arc_number / partial
        # unique is_current constraints and crash.
        next_num = (PlotArc.objects.aggregate(m=Max("arc_number")).get("m") or 0) + 1
        has_current = PlotArc.objects.filter(is_current=True).exists()
        PlotArc.objects.create(
            arc_number=next_num,
            name=PLOT_ARC_NAME,
            description="The sandbox's default story arc.",
            arc_type=PlotArc.ArcType.STORY,
            is_current=not has_current,
        )
        PlotThread.create_thread(
            name=PLOT_THREAD_NAME,
            creator=None,
            description="A seeded thread — link scenes/posts/events to it and conclude it.",
        )
        return 1, 1

    # ------------------------------------------------------------------
    # Regions and maps
    # ------------------------------------------------------------------

    def _create_region(self, rooms):
        """Put every seeded room in one region, each flagged primary.

        Mirrors what +region/add-room does, including the is_primary flag on a
        room's first membership: the map's primary_region overlay, the region
        page's room list, and lore's has_lore overlay all read that one
        deterministic answer per room.
        """
        from evennia_regions.models import Region, RegionMembership

        region = Region.create_region(
            name=REGION_NAME,
            creator=None,
            description="Everything within a short walk of the Sandbox Plaza.",
        )
        for name, room in rooms.items():
            if name == OOC_ROOM_NAME:
                # An OOC hub is not IC geography. No tile, no membership - so
                # the primary_region overlay and the region page's room list
                # both stay honestly in-character.
                continue
            RegionMembership.objects.create(
                region=region,
                room=room,
                room_name=name,
                is_primary=True,
            )
        return region

    def _create_map(self, rooms):
        """Place the origin tile, then let layout derive the other five.

        Only one coordinate pair is written by hand. layout.plan() walks the
        canonical-direction exits out from the origin and returns the moves
        that are mutually safe to write; placement.apply_plan() writes exactly
        that set. Seeding it this way rather than with six literal (x, y) pairs
        means the seed exercises the same code path a builder's +map/reflow
        does, and a broken direction alias in ROOM_LINKS surfaces as a missing
        tile rather than a silently wrong-but-placed grid.
        """
        from evennia_maps import layout, placement
        from evennia_maps.models import MapPlane, RoomTile

        plane = MapPlane.objects.create(
            name=PLANE_NAME,
            zstack="overworld",
            elevation=0,
            description="The surface layer of the sandbox's one and only continent.",
        )
        origin = rooms[ORIGIN_ROOM_NAME]
        # Pinned: the origin anchors the derived grid, so a later +map/reflow
        # started from somewhere else must not move it.
        placement.place_tile(origin, plane, 0, 0, pinned=True)
        placement.apply_plan(layout.plan(origin))
        return RoomTile.objects.filter(plane=plane).count()

    def _create_scenes(self, rooms):
        """One live scene and one closed one, positioned to light the overlays.

        The live scene sits in the Consulate Hall (has_active_scene, and — once
        _link_overlays() attaches the event to it — upcoming_events); the
        closed one sits in the Archive, which is what the heatmap
        (recent_scene_count) and the popup's log links (recent_scenes) read.
        Both are PUBLIC, so they show for anonymous web visitors rather than
        for staff only. Returns (count, the live scene) — _link_overlays()
        needs the live one, since a calendar event reaches a room only through
        a scene.
        """
        from evennia_scenes.models import Scene

        hall = rooms["Consulate Hall"]
        live = Scene.objects.create(
            title=SCENE_TITLES[0],
            description="Doors open early; someone is already blocking out the staging.",
            room=hall,
            room_name=hall.key,
            privacy=Scene.Privacy.PUBLIC,
            status=Scene.Status.OPEN,
        )
        # The room-side half of evennia_scenes' integration contract (see
        # typeclasses/rooms.py): consumers read the pk off the room without
        # importing the contrib.
        hall.active_scene_id = live.pk

        archive = rooms["The Archive"]
        closed = Scene.objects.create(
            title=SCENE_TITLES[1],
            description="Two archivists, one disputed shelf-mark, no witnesses.",
            room=archive,
            room_name=archive.key,
            privacy=Scene.Privacy.PUBLIC,
            status=Scene.Status.OPEN,
        )
        # close() rather than status=CLOSED at creation: close() is what stamps
        # ended_at, and the heatmap window filters on ended_at — a hand-set
        # status would produce a closed scene the map never counts.
        closed.close()
        return 2, live

    def _link_overlays(self, region, entries, event, live_scene):
        """The cross-domain links the tile overlays are actually driven by."""
        from evennia_calendar.models import SceneCalendarLink
        from evennia_lore.models import LoreRegionLink

        count = 0
        # Lore attaches to the region, not to a room: has_lore lights every
        # room whose primary region has at least one published public entry.
        for entry in entries:
            LoreRegionLink.objects.create(entry=entry, region_id=region.pk)
            count += 1
        # An event reaches the map only through a scene — there is no
        # CalendarEvent -> Room field anywhere in the calendar.
        SceneCalendarLink.objects.create(event=event, scene_id=live_scene.pk)
        count += 1
        return count
