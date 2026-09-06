"""The sandbox home page.

Stock Evennia's index shows account counts and database stats. That is the right
default for a fresh game and the wrong one here: this site exists so a playtester
can find the play, and so a developer evaluating the contribs can see at a glance
what the fourteen of them actually put on a website. So the widgets are (1) what
is happening now, (2) what has happened lately, and (3) an inventory of the
systems themselves.

Two rules hold this file together.

**Never re-filter for privacy.** Every queryset below is a copy of the owning
contrib's own list view, cited in the function that builds it. A hand-rolled
filter on the home page is exactly how a private scene reaches an anonymous
visitor - and the rules are not guessable: Scene.WEB_READABLE_PRIVACY is a
membership test rather than "!= VIEW_PRIVATE" precisely so a tier added later
fails closed, and PlotThread's public list deliberately includes INVITE_ONLY.
When a contrib changes its mind about what is public, the correct outcome is
that this page is already wrong in the same direction rather than silently
right.

**Never assume a contrib is installed.** Each widget is gated on
``apps.is_installed()`` and imports inside the function, so dropping a contrib
from INSTALLED_APPS costs one card and not the home page. That mirrors how the
contribs gate their own cross-contrib integrations, and it is the same contract
web/website/nav.py applies to the menu.
"""

from datetime import timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from django.apps import apps
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from evennia.web.website.views.index import EvenniaIndexView

# Feed windows. Deliberately generous: a sandbox can sit quiet for a week and the
# home page should still have something on it.
ACTIVITY_WINDOW_DAYS = 30
ACTIVITY_LIMIT = 10
WIDGET_LIMIT = 5

# Contribs with no web surface at all. Listed on the systems widget so the
# inventory is honest about the whole install rather than only the linkable part
# of it - "in-game only" is information a developer evaluating the repo wants.
IN_GAME_ONLY = (
    ("evennia_links", "Abstract bridge, versioning and archiving models"),
    ("evennia_rptracker", "Passive RP-session activity tracking"),
    ("evennia_posing", "Pose, emit, semipose and pose-order tracking"),
    ("evennia_social", "Profiles, discovery, paging, filtering, teleport"),
    ("evennia_accessibility", "Screenreader mode and accessible form partials"),
)


def _url(name, *args):
    """``reverse()`` that returns None instead of raising. Same contract as nav.py."""
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def _dist(app_label):
    """Installed version of the distribution providing *app_label*, or "".

    Read from the installed dist metadata rather than the package's own
    ``__version__``, which is the value that goes stale when a release bumps
    pyproject and nothing else.
    """
    try:
        return _dist_version(app_label.replace("_", "-"))
    except PackageNotFoundError:
        return ""


def _live_scenes():
    """Scenes running right now.

    Mirrors evennia_scenes.integrations.maps._active_scene_room_ids, which is the
    contrib's own answer for "where is play happening" and applies
    WEB_READABLE_PRIVACY. Not SceneListView: that lists CLOSED scenes, which is
    the opposite end of a scene's life.
    """
    if not apps.is_installed("evennia_scenes"):
        return []
    from evennia_scenes.models import Scene

    scenes = Scene.objects.filter(
        status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE),
        privacy__in=Scene.WEB_READABLE_PRIVACY,
    ).order_by("-started_at")[:WIDGET_LIMIT]
    return [
        {
            "title": scene.title or f"Scene #{scene.pk}",
            "room": scene.room_name,
            "started_at": scene.started_at,
            # Detail pages are CLOSED-only, so a running scene has nothing to
            # link to yet. The card links to the archive as a whole instead.
            "url": None,
        }
        for scene in scenes
    ]


def _upcoming_events():
    """Next few events. Mirrors evennia_calendar.views.CalendarListView.

    No is_staff_event filter, deliberately: that flag selects lottery RSVP mode
    and blocks pre-invites (anti-favoritism). It is not a visibility tier, and
    none of the calendar's own web views treat it as one.
    """
    if not apps.is_installed("evennia_calendar"):
        return []
    from evennia_calendar.models import CalendarEvent

    events = (
        CalendarEvent.objects.filter(is_cancelled=False, scheduled_time__gte=timezone.now())
        .prefetch_related("tags")
        .order_by("scheduled_time")[:WIDGET_LIMIT]
    )
    return [
        {
            "title": event.title,
            "scheduled_time": event.scheduled_time,
            "url": _url("evennia_calendar:calendar-event-detail", event.pk),
        }
        for event in events
    ]


def _map_summary():
    """Plane and tile counts, and the deepest map link that resolves."""
    if not apps.is_installed("evennia_maps"):
        return None
    from evennia_maps.models import MapPlane, RoomTile

    # MapPlane.objects is an ArchivedManager, so archived planes are already out.
    planes = MapPlane.objects.order_by("pk")
    first = planes.first()
    if first is None:
        return None
    return {
        "plane_count": planes.count(),
        "tile_count": RoomTile.objects.filter(plane__in=planes).count(),
        "plane_name": first.name,
        "url": (
            _url("evennia_maps:plane-live-map", first.pk)
            or _url("evennia_maps:plane-detail", first.pk)
            or _url("evennia_maps:plane-list")
        ),
    }


def _recent_activity():
    """One time-ordered feed across the four contribs that publish public rows.

    Plot *updates* are deliberately absent even though they are the most
    narrative rows available: PlotUpdate carries its own IC/OOC rule (OOC blocks
    are participants-and-staff only) and there is no public queryset for them to
    copy. New threads stand in - PlotListView's exact filter, no new reasoning.
    """
    cutoff = timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
    rows = []

    if apps.is_installed("evennia_scenes"):
        from evennia_scenes.models import Scene

        # evennia_scenes.views.SceneListView.get_queryset
        for scene in Scene.objects.filter(
            status=Scene.Status.CLOSED,
            privacy__in=Scene.WEB_READABLE_PRIVACY,
            ended_at__gte=cutoff,
        ).order_by("-ended_at")[:ACTIVITY_LIMIT]:
            rows.append(
                {
                    "kind": "Scene",
                    "label": scene.title or f"Scene #{scene.pk}",
                    "when": scene.ended_at,
                    "url": _url("evennia_scenes:scene-detail", scene.pk),
                }
            )

    if apps.is_installed("evennia_lore"):
        from evennia_lore.models import LoreEntry

        # evennia_lore.views.LoreListView.get_queryset
        for entry in LoreEntry.objects.filter(
            status=LoreEntry.Status.PUBLISHED,
            is_archived=False,
            created_at__gte=cutoff,
        ).order_by("-created_at")[:ACTIVITY_LIMIT]:
            rows.append(
                {
                    "kind": "Lore",
                    "label": entry.title,
                    "when": entry.created_at,
                    "url": _url("lore-detail", entry.pk),
                }
            )

    if apps.is_installed("evennia_boards"):
        from evennia_boards.models import Post

        # Post.objects is an ArchivedManager; boards carry no privacy tier, which
        # is why evennia_boards.views.BoardListView filters on nothing.
        for post in (
            Post.objects.filter(created_at__gte=cutoff)
            .select_related("board")
            .order_by("-created_at")[:ACTIVITY_LIMIT]
        ):
            rows.append(
                {
                    "kind": "Post",
                    "label": f"{post.title} ({post.board.name})",
                    "when": post.created_at,
                    "url": _url("evennia_boards:board-detail", post.board_id),
                }
            )

    if apps.is_installed("evennia_plots"):
        from evennia_plots.models import PlotThread

        # evennia_plots.views.PlotListView.get_queryset - INVITE_ONLY is public
        # to *list*, which is the contrib's call and not this page's to revisit.
        for thread in PlotThread.objects.filter(
            status=PlotThread.Status.ACTIVE,
            privacy__in=[PlotThread.Privacy.PUBLIC, PlotThread.Privacy.INVITE_ONLY],
            created_at__gte=cutoff,
        ).order_by("-created_at")[:ACTIVITY_LIMIT]:
            rows.append(
                {
                    "kind": "Plot",
                    "label": thread.name,
                    "when": thread.created_at,
                    "url": _url("evennia_plots:plot-detail", thread.pk),
                }
            )

    rows.sort(key=lambda row: row["when"], reverse=True)
    return rows[:ACTIVITY_LIMIT]


def _current_arc():
    """The staff-designated current arc, if there is one.

    Only the arc's own public fields; plot-arc-list is staff-only, so the card
    never links there.
    """
    if not apps.is_installed("evennia_plots"):
        return None
    from evennia_plots.models import PlotArc

    arc = PlotArc.objects.filter(is_current=True).first()
    if arc is None:
        return None
    return {"name": arc.name, "description": arc.description}


def _systems():
    """The install inventory: what is here, and where it surfaces on the web.

    Built from nav.NAV_GROUPS so it cannot drift from the menu - a contrib that
    gains a page and a menu entry appears here without touching this function.
    """
    from web.website.nav import NAV_GROUPS

    seen = set()
    rows = []
    for _group, table in NAV_GROUPS:
        for label, route, _gate in table:
            # Namespaced routes name their app directly. The bare ones (lore,
            # jobs, xp) do not, so fall back to the label - and Characters and
            # Channels resolve to nothing, which is correct: they are Evennia's
            # own pages, not contribs.
            app_label = route.split(":")[0] if ":" in route else f"evennia_{label.lower()}"
            if not apps.is_installed(app_label) or app_label in seen:
                continue
            seen.add(app_label)
            rows.append(
                {
                    "name": app_label,
                    "version": _dist(app_label),
                    "label": label,
                    "url": _url(route),
                }
            )

    for app_label, blurb in IN_GAME_ONLY:
        if apps.is_installed(app_label):
            rows.append(
                {"name": app_label, "version": _dist(app_label), "label": blurb, "url": None}
            )
    return rows


class SandboxIndexView(EvenniaIndexView):
    """Evennia's index view, with this sandbox's widgets added to the context.

    Subclassed rather than replaced so the stock context (account counts,
    recently-connected list) stays available to the template - the
    recently-connected widget is kept, because a sandbox that looks inhabited is
    more useful to a playtester than one that looks empty.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "live_scenes": _live_scenes(),
                "scene_archive_url": _url("evennia_scenes:scene-list"),
                "upcoming_events": _upcoming_events(),
                "calendar_url": _url("evennia_calendar:calendar-list"),
                "map_summary": _map_summary(),
                "recent_activity": _recent_activity(),
                "current_arc": _current_arc(),
                "plot_list_url": _url("evennia_plots:plot-list"),
                "systems": _systems(),
            }
        )
        return context
