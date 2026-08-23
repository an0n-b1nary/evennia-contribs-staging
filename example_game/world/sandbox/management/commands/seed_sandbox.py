"""
Management command: seed_sandbox

Idempotent content-only reset: purges everything this command previously
created, then rebuilds a default world touching every installed contrib, so a
fresh sandbox has populated data to test against immediately.

Does NOT touch accounts/characters — see scripts/reset_to_golden.sh for a
full wipe-to-default (accounts included).

**No prose lives here.** Every player-visible string comes from
world/sandbox/content.py, keyed by a stable slug. That split exists because
the two halves have different lifetimes: names are identity to the purge
below, prose is not.

The world has two halves
------------------------
- **The OOC wing** (content.OOC_ROOMS) — a hub and seven spokes, one per
  command family, each with a plaque naming its commands. Typed
  ``room_type="ooc"``, which settings.MAPS_UNMAPPABLE_ROOM_TYPES declares
  off-map, and joined by *direction-less* exits. Belt and braces on purpose:
  the flavor exits keep the wing out of layout.plan() (a read path), the room
  type keeps it out of the auto-placement listener (a write path a flavor exit
  stops protecting the moment somebody digs a real direction).
- **The IC world** (content.IC_ROOMS) - mapped, region-membered, no plaques.
  Reached through the single direction-less boundary exit from the hub.
  Seventeen rooms on three planes: a nine-room surface, a four-room undercroft
  one elevation down in the same zstack, and a four-room standalone interior
  reached through a portal. Almost every coordinate is *derived* rather than
  written - see _create_map() - and the handful of deliberate exceptions all
  exist to give some read-only map tool something to report. content.py's
  "Deliberate map defects" section is the index of those.

Three rooms outlive a purge
---------------------------
Evennia objects are purged by tag ("sandbox_default", category "sandbox") via
search_tag, then recreated — Evennia's batch processors are not idempotent on
their own, so this command does the purge/rebuild itself rather than replaying
a .ev/.py batch file. Rooms carrying STABLE_TAG instead are re-dressed in
place, never deleted:

- **The Arrival Hall** is dbref #2. settings.START_LOCATION and DEFAULT_HOME
  must hold *dbrefs* — Evennia resolves them with ObjectDB.objects.get_id(),
  which does not take names — so a hall created fresh each run would move out
  from under them and strand every new character. Limbo #2 is made once by
  `evennia migrate` and never deleted, so it is the one dbref stable across
  both a reseed and a golden-DB restore. See _spawn_room().
- **The Drafting Room** survives so that rooms a playtester digs off it, and
  the scratch-plane tiles those rooms hold, stay reachable. Purging it would
  cascade its exits away and orphan every room built through it, which would
  make a liar of the room's own plaque.
- **The scratch plane** (content.DRAFTING_PLANE_NAME) is get_or_create'd rather
  than purged, for the same reason: deleting the plane cascades to every tile
  on it, including the playtester's.

Non-Evennia (plain Django) content - boards, posts, calendar events, lore
entries, plot threads/arcs, regions, the IC planes, scenes - has no tag
mechanism, so it is purged by the fixed names in content.py before being
recreated.

Usage:
    evennia seed_sandbox
    evennia seed_sandbox --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from world.sandbox import content

SANDBOX_TAG = "sandbox_default"
SANDBOX_TAG_CATEGORY = "sandbox"

# Rooms that are re-dressed rather than rebuilt. Same category, different tag,
# so one search_tag call finds each set and neither can drift from the other.
STABLE_TAG = "sandbox_stable"

# Slugs of the rooms carrying STABLE_TAG. See the module docstring for why each
# one earns its exemption.
STABLE_ROOM_SLUGS = (content.ARRIVAL_SLUG, "drafting")

# Names used to purge the plain-Django rows. Derived from content.py rather
# than restated, so renaming something there cannot leave an orphan here.
BOARD_NAMES = [board["name"] for board in content.BOARDS]
LORE_TITLES = [entry["title"] for entry in content.LORE_ENTRIES]
SCENE_TITLES = [scene["title"] for scene in content.SCENES]
PLOT_ARC_NAME = content.PLOT_ARC["name"]
PLOT_THREAD_NAME = content.PLOT_THREAD["name"]
CALENDAR_EVENT_TITLES = [event["title"] for event in content.CALENDAR_EVENTS]
REGION_NAMES = [region["name"] for region in content.REGIONS]

# The three IC planes. The scratch plane is deliberately not in this list -
# see _purge().
PLANE_NAMES = [name for name, _zstack, _elev, _desc in content.IC_PLANES]
PLANE_NAME = content.PLANE_NAME

# The OOC hub, which settings.OOC_ROOM_DBREF names *by name* (evennia_social
# resolves it with search_object, which matches names as well as dbrefs).
OOC_ROOM_NAME = content.OOC_ROOMS_BY_SLUG[content.ARRIVAL_SLUG].name

# Room typing. Everything in the OOC wing is "ooc"; everything in the IC world
# is "ic". The map, the region and evennia_rptracker all read this attribute,
# and MAPS_UNMAPPABLE_ROOM_TYPES turns the first list into an enforced rule.
OOC_ROOM_NAMES = tuple(room.name for room in content.OOC_ROOMS)
IC_ROOM_NAMES = tuple(room.name for room in content.IC_ROOMS)

# Rooms that take a tile somewhere in the IC world: every IC room except the
# ones content.py deliberately leaves off the map. Tests count against this
# rather than against every room, so "not every room is mapped" stays an
# asserted property instead of an off-by-one.
MAPPED_ROOM_NAMES = [
    room.name for room in content.IC_ROOMS if room.slug not in content.UNMAPPED_SLUGS
]

# The room the overworld grid is anchored on: the one tile placed by hand,
# from which layout.plan() derives the rest.
ORIGIN_ROOM_NAME = content.IC_ROOMS_BY_SLUG[content.MAP_ORIGIN_SLUG].name


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

        events = CalendarEvent.objects.filter(title__in=CALENDAR_EVENT_TITLES)
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

        regions = Region.all_objects.filter(name__in=REGION_NAMES)
        counts["regions"] = regions.count()
        if not dry_run:
            regions.delete()  # cascades to RegionMembership

        from evennia_maps.models import MapPlane

        # The three IC planes only. The scratch plane is deliberately absent:
        # deleting it cascades to every tile on it, and the tiles a playtester
        # earned by digging off the Drafting Room are exactly what a content
        # reset promises to leave alone.
        planes = MapPlane.all_objects.filter(name__in=PLANE_NAMES)
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
        counts["objects"] = self._create_plaques(rooms)
        counts["boards"] = self._create_boards()
        events = self._create_calendar_events()
        counts["calendar_events"] = len(events)
        entries = self._create_lore()
        counts["lore_entries"] = len(entries)
        counts["plot_arcs"], counts["plot_threads"] = self._create_plot()

        # Regions and maps come after the rooms and exits they describe, and
        # before the scenes/links that light the tile overlays.
        regions = self._create_regions(rooms)
        counts["regions"] = len(regions)
        counts["region_memberships"] = sum(r.memberships.count() for r in regions.values())
        counts["map_tiles"] = self._create_map(rooms)
        counts["scratch_tiles"] = self._create_scratch_plane(rooms)
        scenes = self._create_scenes(rooms)
        counts["scenes"] = len(scenes)
        counts["overlay_links"] = self._link_overlays(regions, entries, events, scenes)
        return counts

    def _tag(self, obj):
        obj.tags.add(SANDBOX_TAG, category=SANDBOX_TAG_CATEGORY)

    def _tag_stable(self, obj):
        obj.tags.add(STABLE_TAG, category=SANDBOX_TAG_CATEGORY)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    def _spawn_room(self):
        """Return the permanent room settings.START_LOCATION points at.

        This is the Arrival Hall, and the seeder re-dresses it rather than
        creating it. The reason is that START_LOCATION/DEFAULT_HOME must be
        dbrefs: Evennia resolves them with ObjectDB.objects.get_id(), which
        does not accept names. A hall created fresh each run would take a new
        dbref every time and leave those settings pointing at a deleted room,
        so every new character would spawn nowhere.

        Limbo (#2) is created once by `evennia migrate` and never deleted, so
        it is the only dbref stable across both a reseed and a golden-DB
        restore. It carries STABLE_TAG, not SANDBOX_TAG, so _purge() leaves it.
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

    def _stable_room(self, slug):
        """Find a STABLE_TAG room by slug, or create one if this is a first run.

        Found by tag rather than by name so that renaming the room - which a
        playtester can do the moment they take Builder - cannot orphan it and
        leave the next reseed building a duplicate beside it.
        """
        from evennia.utils import create
        from evennia.utils.search import search_tag

        tagged = [
            obj
            for obj in search_tag(STABLE_TAG, category=SANDBOX_TAG_CATEGORY)
            if obj.db.sandbox_slug == slug
        ]
        if tagged:
            return tagged[0]
        room = create.create_object("typeclasses.rooms.Room", key=slug)
        self._tag_stable(room)
        return room

    def _create_rooms(self):
        """Build both halves of the world, keyed by slug.

        Returns a dict of {slug: room}. Slugs rather than names because names
        are display text the user is expected to edit, and a rename must not
        silently repoint an exit table or a region membership.
        """
        from evennia.utils import create

        rooms = {}

        for spec in content.OOC_ROOMS:
            if spec.slug == content.ARRIVAL_SLUG:
                room = self._spawn_room()
                self._tag_stable(room)
            elif spec.slug in STABLE_ROOM_SLUGS:
                room = self._stable_room(spec.slug)
            else:
                room = create.create_object("typeclasses.rooms.Room", key=spec.name)
                self._tag(room)
            room.key = spec.name
            room.db.desc = spec.desc
            # The slug is what _stable_room() matches on across runs, and what
            # tests assert against. Stored on the room rather than inferred
            # from the key, which is the thing that changes.
            room.db.sandbox_slug = spec.slug
            # Reset rather than assume: a stable room survives every purge, so
            # anything a builder changed on it last session is still here.
            room.room_type = "ooc"
            room.set_terrain(None)
            rooms[spec.slug] = room

        for spec in content.IC_ROOMS:
            room = create.create_object("typeclasses.rooms.Room", key=spec.name)
            self._tag(room)
            room.db.desc = spec.desc
            room.db.sandbox_slug = spec.slug
            # "staff" is one of the two room types evennia_maps hardcodes as
            # never web-visible (permissions.py). Unlike "ooc" it is a privacy
            # rule, not cosmology: the room *is* placed on the grid, and the
            # tile is then withheld from every non-staff reader - which is why
            # a playtester can watch it appear by running +sandbox/builder on.
            room.room_type = "staff" if spec.slug == content.STAFF_ROOM_SLUG else "ic"
            # Read duck-typed by evennia_maps (views.tile_hangout_type) and by
            # evennia_social's +hangouts, off the same attribute. None for
            # every room content.py does not name.
            room.hangout_type = content.HANGOUTS.get(spec.slug)
            # MapsRoomMixin (typeclasses/rooms.py). set_terrain() rather than
            # assigning terrain_tags, so terrain_changed fires and any tile
            # already placed for this room refreshes its snapshot. Here the
            # tiles do not exist yet, so it is place_tile() that reads these
            # — the call still goes through the mixin so the seeded world
            # matches what a builder typing the same thing would produce.
            room.set_terrain(set(spec.terrain) or None)
            rooms[spec.slug] = room

        return rooms

    def _create_exits(self, rooms):
        """Wire the hub-and-spoke wing, the IC grid, and the one boundary.

        Only content.IC_LINKS carries direction aliases. evennia_maps' layout
        walks exits it can resolve to a canonical direction, matching the key
        *or* any alias — so "go archive" still works while the map still knows
        the Archive is north. Everything in the OOC wing, the boundary exit,
        and content.IC_FLAVOR_LINKS deliberately carry none, so none of them
        extend the grid.

        Exits are created before any tile exists, so the auto-placement
        listener (evennia_maps.listeners) no-ops throughout; _create_map()
        derives the whole grid in one pass instead.
        """
        count = 0

        # Hub to each spoke and back. Direction-less by construction: the keys
        # come from content.OOC_SPOKE_EXIT_KEYS and no alias is ever attached.
        hub = rooms[content.ARRIVAL_SLUG]
        for slug in content.OOC_SPOKE_SLUGS:
            out_key, back_key = content.OOC_SPOKE_EXIT_KEYS[slug]
            count += self._link(hub, rooms[slug], out_key, back_key)

        # The one door between the two halves.
        out_key, back_key = content.IC_BOUNDARY_EXIT_KEYS
        count += self._link(hub, rooms[content.IC_ENTRY_SLUG], out_key, back_key)

        # The IC grid: the only exits the map can walk.
        for a_slug, b_slug, (a_key, a_dir), (b_key, b_dir) in content.IC_LINKS:
            count += self._link(
                rooms[a_slug], rooms[b_slug], a_key, b_key, a_alias=a_dir, b_alias=b_dir
            )

        # An IC exit with no direction alias, so the map visibly does not grow
        # through it. Demonstrating the trap beats hiding it.
        for a_slug, b_slug, a_key, b_key in content.IC_FLAVOR_LINKS:
            count += self._link(rooms[a_slug], rooms[b_slug], a_key, b_key)

        return count

    def _link(self, a, b, a_key, b_key, *, a_alias=None, b_alias=None):
        """Create a bidirectional exit pair. Returns the number made (2)."""
        from evennia.utils import create

        for source, destination, key, alias in (
            (a, b, a_key, a_alias),
            (b, a, b_key, b_alias),
        ):
            exit_obj = create.create_object(
                "typeclasses.exits.Exit",
                key=key,
                aliases=[alias] if alias else None,
                location=source,
                destination=destination,
            )
            self._tag(exit_obj)
        return 2

    def _create_plaques(self, rooms):
        """One plaque per OOC room, naming that room's command family.

        The framing sentence is the user's (content.OocRoom.plaque); the list
        of commands under it is rendered from OocRoom.commands, which is
        documentation rather than prose. IC rooms get none — they are meant to
        read as setting, not as a tutorial.
        """
        from evennia.utils import create

        count = 0
        for spec in content.OOC_ROOMS:
            plaque = create.create_object(
                "typeclasses.objects.Object",
                key=content.PLAQUE_KEY,
                location=rooms[spec.slug],
            )
            lines = [spec.plaque]
            if spec.commands:
                lines += ["", "Commands demonstrated here:"]
                lines += [f"  {command}" for command in spec.commands]
            plaque.db.desc = "\n".join(lines)
            self._tag(plaque)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Django-row content
    # ------------------------------------------------------------------

    def _create_boards(self):
        # Django-model content (boards/posts and the calendar/lore/plot rows
        # below) has no Evennia tag handler, so it's purged by name/title in
        # _purge() rather than by the sandbox_default tag.
        from evennia_boards.models import Board, Post

        by_slug = {}
        board_types = {"general": Board.BoardType.OOC, "cutscenes": Board.BoardType.IC}
        for order, spec in enumerate(content.BOARDS):
            by_slug[spec["slug"]] = Board.objects.create(
                name=spec["name"],
                description=spec["description"],
                board_type=board_types.get(spec["slug"], Board.BoardType.OOC),
                order=order,
            )

        post = content.BOARD_FIRST_POST
        Post.create_post(
            board=by_slug[post["board_slug"]],
            author=None,
            title=post["title"],
            content=post["body"],
        )
        return len(by_slug)

    def _create_calendar_events(self):
        """One open event and one staff-only one, both in the future.

        Both must be in the future or the map never shows them at all: the
        upcoming_events overlay filters on scheduled_time >= now. The
        staff-only one carries is_staff_event, which the same overlay withholds
        from non-staff - so the pair is what makes the visibility rule visible,
        one event before +sandbox/builder on and two after.

        Returned as {slug: event} rather than counted, because _link_overlays()
        attaches each to a scene: that link is the only path an event has to a
        room, and so the only way either reaches the map at all.
        """
        from datetime import UTC, datetime, timedelta

        from evennia_calendar.models import CalendarEvent

        events = {}
        for offset, spec in enumerate(content.CALENDAR_EVENTS):
            events[spec["slug"]] = CalendarEvent.create_event(
                creator=None,
                title=spec["title"],
                # Staggered so the calendar page and the popup have a stable
                # soonest-first order rather than a pk tiebreak.
                scheduled_time=datetime.now(UTC) + timedelta(days=7 + offset),
                description=spec["description"],
                emphasis=CalendarEvent.Emphasis.FREEFORM,
                is_staff_event=spec["staff_only"],
            )
        return events

    def _create_lore(self):
        from evennia_lore.models import LoreEntry

        # Returned so _link_overlays() can attach these to the region — lore
        # hangs off regions, never off rooms, which is why the has_lore overlay
        # resolves each room's primary region before it can answer.
        return [
            LoreEntry.create_entry(
                title=spec["title"],
                author=None,
                body=spec["body"],
                privacy=LoreEntry.Privacy.PUBLIC,
            )
            for spec in content.LORE_ENTRIES
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
            name=content.PLOT_ARC["name"],
            description=content.PLOT_ARC["description"],
            arc_type=PlotArc.ArcType.STORY,
            is_current=not has_current,
        )
        PlotThread.create_thread(
            name=content.PLOT_THREAD["name"],
            creator=None,
            description=content.PLOT_THREAD["description"],
        )
        return 1, 1

    # ------------------------------------------------------------------
    # Regions and maps
    # ------------------------------------------------------------------

    def _create_regions(self, rooms):
        """Build the three regions and every IC room's membership in them.

        Mirrors what +region/add-room does, including the is_primary flag: at
        most one membership per room may carry it (the DB enforces that), and
        it is the single deterministic answer the map's primary_region overlay,
        the region page's room list and lore's has_lore overlay all read.

        Two arrangements here are deliberate rather than incidental:

        - **Market Row has two memberships**, primary in the Commons and plain
          on the Waterfront. The region pages list it twice; the tile label
          stays one answer.
        - **The Undercity is archived**, and the undercroft rooms' *flagged*
          primary membership is in it. RegionMembership.primary_for() would
          answer "the Undercity" for those rooms; the map's overlay
          deliberately diverges and skips archived regions, so their tiles
          label as the Waterfront instead. Archiving happens after the
          memberships are written - Region.create_region() has no archived
          argument, and archiving first would not change the result anyway.

        The OOC wing is absent from all three. An OOC room is not IC geography
        - no tile, no membership - so the primary_region overlay and the region
        pages stay honestly in-character. Same set the map treats as
        off-limits, for the same reason.

        Returns {slug: Region}.
        """
        from evennia_regions.models import Region, RegionMembership

        regions = {}
        for spec in content.REGIONS:
            regions[spec["slug"]] = Region.create_region(
                name=spec["name"],
                creator=None,
                description=spec["description"],
            )

        for spec in content.IC_ROOMS:
            primary_slug, secondary_slugs = content.IC_REGION_MEMBERSHIPS[spec.slug]
            for region_slug, is_primary in [(primary_slug, True)] + [
                (slug, False) for slug in secondary_slugs
            ]:
                RegionMembership.objects.create(
                    region=regions[region_slug],
                    room=rooms[spec.slug],
                    room_name=spec.name,
                    is_primary=is_primary,
                )

        for spec in content.REGIONS:
            if spec["archived"]:
                regions[spec["slug"]].archive()

        return regions

    def _create_map(self, rooms):
        """Build all three IC planes: two derived walks and a short list of defects.

        Two coordinate pairs are written by hand for the whole IC world, and
        both are origins. Everything else on the surface and in the undercroft
        is derived: layout.plan() walks the canonical-direction exits out from
        the plaza and returns the moves that are mutually safe to write, and
        placement.apply_plan() writes exactly that set. Seeding it this way
        rather than with literal (x, y) pairs means the seed exercises the same
        code path a builder's +map/reflow does, and a broken direction alias in
        content.IC_LINKS surfaces as a missing tile rather than as a silently
        wrong-but-placed grid.

        The undercroft comes along for free. A `down` exit is a *vertical*
        direction (direction.py), so the same walk crosses into the adjacent
        elevation of the same zstack at the same (x, y) - four rooms placed
        without a coordinate written for any of them. The plane rows are
        pre-created only so they carry the names content.py gives them:
        resolve_stacked_plane() would scaffold the -1 plane by itself, but
        would call it "overworld (-1)".

        The interior is a second, separate walk. Nothing reaches it by
        direction - the doors from Consulate Hall are a plain exit - and that
        is precisely what makes it a portal rather than a neighbour, so it
        needs an anchor of its own.

        Then three defects are applied, in this order for a reason each. See
        content.py's "Deliberate map defects" section for what each one is for.
        """
        from evennia_maps import layout, placement
        from evennia_maps.models import MapPlane, RoomTile

        planes = {}
        for name, zstack, elevation, description in content.IC_PLANES:
            planes[name] = MapPlane.objects.create(
                name=name,
                zstack=zstack,
                elevation=elevation,
                description=description,
            )

        # The surface, and the undercroft under it.
        origin = rooms[content.MAP_ORIGIN_SLUG]
        # Pinned: the origin anchors the derived grid, so a later +map/reflow
        # started from somewhere else must not move it.
        placement.place_tile(origin, planes[content.PLANE_NAME], 0, 0, pinned=True)
        placement.apply_plan(layout.plan(origin))

        # The interior, from its own anchor.
        interior_origin = rooms[content.INTERIOR_ORIGIN_SLUG]
        placement.place_tile(
            interior_origin, planes[content.INTERIOR_PLANE_NAME], 0, 0, pinned=True
        )
        placement.apply_plan(layout.plan(interior_origin))

        # Defect 1: rooms with no tile at all, though a direction exit reaches
        # them from a room that has one. Placed and then removed rather than
        # skipped, because the walk derives them whether or not we want it to -
        # and because a deleted tile is exactly what the state being
        # demonstrated (a room dug before the map existed) leaves behind.
        RoomTile.objects.filter(room__in=[rooms[slug] for slug in content.UNMAPPED_SLUGS]).delete()

        # Defect 2: tiles at coordinates the walk disagrees with, so
        # +map/reflow has a two-step blocked cascade to report. Deleted first,
        # then re-placed: these coordinates are a rotation of the derived ones,
        # so there is no free cell to start an in-place move from and every
        # ordering of move_tile() calls would hit the (plane, x, y) unique
        # constraint.
        misplaced = content.MISPLACED_TILES
        RoomTile.objects.filter(
            room__in=[rooms[slug] for slug, _x, _y, _pinned in misplaced]
        ).delete()
        for slug, x, y, pinned in misplaced:
            placement.place_tile(
                rooms[slug], planes[content.UNDERCROFT_PLANE_NAME], x, y, pinned=pinned
            )

        return RoomTile.objects.filter(plane__name__in=PLANE_NAMES).count()

    def _create_scratch_plane(self, rooms):
        """Give the Drafting Room a tile on a plane of its own.

        The room exists so a playtester can `@dig north=Somewhere` and watch
        the map grow, and that only works if the room they dig *from* is
        already mapped: evennia_maps' auto-placement listener bails when the
        source room has no tile (listeners.py), silently, with no error. An
        unmapped Drafting Room would make the whole demo a no-op.

        A separate plane rather than a corner of the overworld, so a
        playtester's experiments never collide with — or vandalise — the IC
        grid. get_or_create rather than create: this plane is not purged, so
        that the tiles they earn survive a content reset along with the rooms.

        The Drafting Room is typed "ooc" like the rest of the wing, so this is
        the one place the seeder places such a tile deliberately. That is
        allowed on purpose — MAPS_UNMAPPABLE_ROOM_TYPES guards the *listener*,
        not the explicit write path — and `+map/check` reports it, which is the
        honest outcome rather than a silent exception.
        """
        from evennia_maps import placement
        from evennia_maps.models import MapPlane, RoomTile

        plane, _ = MapPlane.all_objects.get_or_create(
            name=content.DRAFTING_PLANE_NAME,
            defaults={
                "zstack": "",
                "elevation": 0,
                "description": "Scratch plane: rooms playtesters build for themselves.",
            },
        )
        drafting = rooms["drafting"]
        # Pinned so that a playtester running +map/reflow from one of their own
        # rooms cannot drag the anchor out from under everything else they dug.
        placement.place_tile(drafting, plane, 0, 0, pinned=True)
        return RoomTile.objects.filter(plane=plane).count()

    # ------------------------------------------------------------------
    # Scenes and the overlay links
    # ------------------------------------------------------------------

    def _create_scenes(self, rooms):
        """Scenes placed to light three different overlays on three different tiles.

        One is left open, in Consulate Hall: that is has_active_scene, and -
        once _link_overlays() attaches an event to it - upcoming_events too.
        The rest are closed, and are what the heatmap (recent_scene_count) and
        the popup's log links (recent_scenes) read.

        The closed ones are distributed unevenly on purpose. The heatmap radius
        is min(4 + 2n, 16), so a grid where every room has exactly one closed
        scene demonstrates only that the layer draws; three in the Archive
        against one in Market Row demonstrates that it means something.

        All PUBLIC, so they show for anonymous web visitors rather than for
        staff only. Returns {slug: Scene}.
        """
        from evennia_scenes.models import Scene

        made = {}
        for spec in content.SCENES:
            room = rooms[spec["room_slug"]]
            scene = Scene.objects.create(
                title=spec["title"],
                description=spec["description"],
                room=room,
                room_name=room.key,
                privacy=Scene.Privacy.PUBLIC,
                status=Scene.Status.OPEN,
            )
            if spec["closed"]:
                # close() rather than status=CLOSED at creation: close() is
                # what stamps ended_at, and the heatmap window filters on
                # ended_at - a hand-set status would produce a closed scene the
                # map never counts.
                scene.close()
            else:
                # The room-side half of evennia_scenes' integration contract
                # (see typeclasses/rooms.py): consumers read the pk off the
                # room without importing the contrib.
                room.active_scene_id = scene.pk
            made[spec["slug"]] = scene
        return made

    def _link_overlays(self, regions, entries, events, scenes):
        """The cross-domain links the tile overlays are actually driven by.

        Lore goes to one region only (content.LORE_REGION_SLUG). Attaching it
        to all three would light every tile, and an overlay that is true
        everywhere is indistinguishable from one that is broken.
        """
        from evennia_calendar.models import SceneCalendarLink
        from evennia_lore.models import LoreRegionLink

        count = 0
        # Lore attaches to a region, not to a room: has_lore lights every room
        # whose primary region has at least one published public entry.
        lore_region = regions[content.LORE_REGION_SLUG]
        for entry in entries:
            LoreRegionLink.objects.create(entry=entry, region_id=lore_region.pk)
            count += 1
        # An event reaches the map only through a scene - there is no
        # CalendarEvent -> Room field anywhere in the calendar.
        for spec in content.CALENDAR_EVENTS:
            SceneCalendarLink.objects.create(
                event=events[spec["slug"]], scene_id=scenes[spec["scene_slug"]].pk
            )
            count += 1
        return count
