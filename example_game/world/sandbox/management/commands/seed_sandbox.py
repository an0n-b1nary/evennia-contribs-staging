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
entries, plot threads/arcs — has no tag mechanism, so it's purged by a fixed,
recognizable name/title before recreating.

Usage:
    evennia seed_sandbox
    evennia seed_sandbox --dry-run
"""

from django.core.management.base import BaseCommand

SANDBOX_TAG = "sandbox_default"
SANDBOX_TAG_CATEGORY = "sandbox"

# Fixed names/titles used both to purge prior runs and to recreate content.
ROOM_NAMES = ["Sandbox Plaza", "The Archive", "Consulate Hall", "Staff Lounge"]
BOARD_NAMES = ["General", "Cutscenes"]
LORE_TITLES = ["The Founding of the Sandbox", "Rumors from the Archive"]
PLOT_ARC_NAME = "Sandbox Genesis"
PLOT_THREAD_NAME = "The Founding Storm"
CALENDAR_EVENT_TITLE = "Sandbox Kickoff"


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
        mode = "DRY RUN" if dry_run else "LIVE"
        self.stdout.write(self.style.NOTICE(f"seed_sandbox [{mode}]"))

        purged = self._purge(dry_run)
        self.stdout.write(f"Purged: {purged}")

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] Skipping rebuild."))
            return

        created = self._rebuild()
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))

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
        counts["calendar_events"] = self._create_calendar_event()
        counts["lore_entries"] = self._create_lore()
        counts["plot_arcs"], counts["plot_threads"] = self._create_plot()
        return counts

    def _tag(self, obj):
        obj.tags.add(SANDBOX_TAG, category=SANDBOX_TAG_CATEGORY)

    def _create_rooms(self):
        from evennia.utils import create

        rooms = {}
        for name in ROOM_NAMES:
            room = create.create_object(
                "typeclasses.rooms.Room",
                key=name,
            )
            room.db.desc = f"{name}. Default sandbox content — safe to explore and pose in."
            if name == "Staff Lounge":
                room.room_type = "ooc"
            self._tag(room)
            rooms[name] = room
        return rooms

    def _create_exits(self, rooms):
        from evennia.utils import create

        # A simple hub-and-spoke layout, each spoke bidirectional.
        links = [
            ("Sandbox Plaza", "The Archive", "archive", "plaza"),
            ("Sandbox Plaza", "Consulate Hall", "hall", "plaza"),
            ("Sandbox Plaza", "Staff Lounge", "lounge", "plaza"),
        ]
        count = 0
        for a_name, b_name, a_to_b, b_to_a in links:
            a, b = rooms[a_name], rooms[b_name]
            exit_a = create.create_object(
                "typeclasses.exits.Exit",
                key=a_to_b,
                location=a,
                destination=b,
            )
            self._tag(exit_a)
            exit_b = create.create_object(
                "typeclasses.exits.Exit",
                key=b_to_a,
                location=b,
                destination=a,
            )
            self._tag(exit_b)
            count += 2
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
        from evennia_boards.models import Board

        general = Board.objects.create(
            name="General",
            description="OOC discussion.",
            board_type=Board.BoardType.OOC,
            order=0,
        )
        self._tag_django(general)

        cutscenes = Board.objects.create(
            name="Cutscenes",
            description="In-character narrative posts.",
            board_type=Board.BoardType.IC,
            order=1,
        )
        self._tag_django(cutscenes)

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

    def _tag_django(self, instance):
        """Django models have no tag handler; nothing to do here.

        Purge for these is name-based (see _purge). This helper exists only
        to make the "we don't tag Django rows" decision explicit at each
        call site rather than silently absent.
        """

    def _create_calendar_event(self):
        from datetime import UTC, datetime, timedelta

        from evennia_calendar.models import CalendarEvent

        CalendarEvent.create_event(
            creator=None,
            title=CALENDAR_EVENT_TITLE,
            scheduled_time=datetime.now(UTC) + timedelta(days=7),
            description="A seeded open event — RSVP with +rsvp.",
            emphasis=CalendarEvent.Emphasis.FREEFORM,
        )
        return 1

    def _create_lore(self):
        from evennia_lore.models import LoreEntry

        LoreEntry.create_entry(
            title=LORE_TITLES[0],
            author=None,
            body="In the beginning, a handful of rooms and a brass plaque...",
            privacy=LoreEntry.Privacy.PUBLIC,
        )
        LoreEntry.create_entry(
            title=LORE_TITLES[1],
            author=None,
            body="Some say the Archive holds every seed this sandbox has ever grown.",
            privacy=LoreEntry.Privacy.PUBLIC,
        )
        return 2

    def _create_plot(self):
        from evennia_plots.models import PlotArc, PlotThread

        PlotArc.objects.create(
            arc_number=1,
            name=PLOT_ARC_NAME,
            description="The sandbox's default story arc.",
            arc_type=PlotArc.ArcType.STORY,
            is_current=True,
        )
        PlotThread.create_thread(
            name=PLOT_THREAD_NAME,
            creator=None,
            description="A seeded thread — link scenes/posts/events to it and conclude it.",
        )
        return 1, 1
