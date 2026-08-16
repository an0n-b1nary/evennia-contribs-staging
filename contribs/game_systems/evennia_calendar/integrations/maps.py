# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Calendar -> Maps tile overlay: what is about to happen, and where.

evennia_maps asks its installed partners once per map render, via the
``collect_tile_overlays`` collector signal, and this module answers for the
calendar. Nothing to configure: install both contribs and upcoming events
appear in the tile popups; uninstall either and the map renders without
them.

Overlay key
-----------
``upcoming_events`` — ``{room_id: [{"id": int, "title": str}, ...]}``,
soonest first, for non-cancelled events still in the future.

Visibility
----------
Staff-only events are withheld from non-staff, the same rule the calendar's
own web views apply. ``is_staff_event`` exists to stop staff-run events
being visible-but-unjoinable to everyone; a map pin advertising one would
undo that, and evennia_maps has no way to know the flag exists.

How an event reaches a room
---------------------------
There is no CalendarEvent -> Room field. An event reaches the map only once
a Scene has been created for it and linked via ``SceneCalendarLink``, whose
``scene_id`` is an integer soft-ref into evennia_scenes. That contrib is
therefore resolved through ``apps.get_model`` under
``CALENDAR_SCENES_APP_LABEL``, exactly as ``CalendarConfig.ready()``
already resolves it for the soft-ref cleanup hook. With scenes absent
nothing can be located, and the overlay is empty.

Connected from CalendarConfig.ready(), gated on evennia_maps being
installed.
"""

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from evennia_calendar.models import SceneCalendarLink


def _scene_model():
    """The Scene model, or None when evennia_scenes is absent."""
    scenes_label = getattr(settings, "CALENDAR_SCENES_APP_LABEL", "evennia_scenes")
    try:
        return apps.get_model(scenes_label, "Scene")
    except LookupError:
        return None


def _upcoming_events_by_room(room_ids, *, staff):
    """
    ``{room_id: [{"id", "title"}, ...]}`` for upcoming, non-cancelled events,
    reached through the scenes rooted in those rooms.

    Two bulk queries, driven from the *event* side: the upcoming
    un-cancelled events are a handful at any moment, whereas the set of
    scenes ever held in these rooms grows without bound over a game's life.
    Ordered soonest-first so a popup lists them in the order a player cares
    about.
    """
    Scene = _scene_model()
    if Scene is None:
        return {}
    links = SceneCalendarLink.objects.filter(
        event__is_cancelled=False,
        event__scheduled_time__gte=timezone.now(),
    )
    if not staff:
        links = links.filter(event__is_staff_event=False)
    # The title rides along on the join already being made — no extra query.
    rows = list(
        links.order_by("event__scheduled_time", "event_id").values_list(
            "scene_id", "event_id", "event__title"
        )
    )
    if not rows:
        return {}
    scene_room_by_id = dict(
        Scene.objects.filter(
            id__in={scene_id for scene_id, _, _ in rows}, room_id__in=room_ids
        ).values_list("id", "room_id")
    )
    result = {}
    for scene_id, event_id, event_title in rows:
        room_id = scene_room_by_id.get(scene_id)
        if room_id is not None:
            result.setdefault(room_id, []).append(
                {"id": event_id, "title": event_title or f"Event #{event_id}"}
            )
    return result


def provide(sender, room_ids, staff, **kwargs):
    """
    ``collect_tile_overlays`` receiver — see the module docstring for the key.

    Two queries for the whole grid, flat in tile count.
    """
    if not room_ids:
        return {}
    return {"upcoming_events": _upcoming_events_by_room(room_ids, staff=staff)}
