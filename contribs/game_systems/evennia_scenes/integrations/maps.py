# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scenes -> Maps tile overlays: where play is happening, and where it has been.

evennia_maps asks its installed partners once per map render, via the
``collect_tile_overlays`` collector signal, and this module answers for
scenes. Nothing to configure: install both contribs and the overlays
appear; uninstall either and the map renders without them.

This has to be a provider rather than something the map reads for itself.
``Scene.room_id`` is a bare pk with no privacy dimension — a map that
pinned tiles from it directly would announce every view-private scene to
every anonymous visitor. Only this contrib knows
``Scene.WEB_READABLE_PRIVACY``, so only this contrib can answer.

Overlay keys
------------
``has_active_scene``
    ``{room_id: True}`` for rooms with a currently open/active scene.
    Privacy-filtered for non-staff.
``recent_scene_count``
    ``{room_id: int}`` — closed scenes in the last 90 days, the heatmap
    weight. Privacy-filtered for non-staff.
``recent_scenes``
    ``{room_id: [{"id": int, "title": str}, ...]}`` — up to 3 most recent
    closed scenes, newest first. **Always** public-tier, staff included:
    these render as links to log pages, so a staff-only entry here would
    leak by URL to anyone the link is pasted to.

``recent_scene_count`` and ``recent_scenes`` are deliberately *not* in step
for staff. The heatmap is only useful to staff if it shows where play is
actually happening, so a staff tile can read "5 recent scenes" and still
list fewer public logs beneath it.

Connected from ScenesConfig.ready(), gated on evennia_maps being installed.
"""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from evennia_scenes.models import Scene

# Statuses that count as "currently happening" for has_active_scene.
_LIVE_SCENE_STATUSES = (Scene.Status.OPEN, Scene.Status.ACTIVE)

_HEATMAP_WINDOW_DAYS = 90
_RECENT_LOG_LIMIT = 3


def _active_scene_room_ids(room_ids, *, staff):
    """Room ids with a currently open/active scene, privacy-filtered for non-staff."""
    qs = Scene.objects.filter(room_id__in=room_ids, status__in=_LIVE_SCENE_STATUSES)
    if not staff:
        qs = qs.filter(privacy__in=Scene.WEB_READABLE_PRIVACY)
    return set(qs.values_list("room_id", flat=True))


def _recent_scene_counts_by_room(room_ids, *, staff):
    """``{room_id: count}`` of scenes closed within the heatmap window."""
    cutoff = timezone.now() - timedelta(days=_HEATMAP_WINDOW_DAYS)
    qs = Scene.objects.filter(
        room_id__in=room_ids, status=Scene.Status.CLOSED, ended_at__gte=cutoff
    )
    if not staff:
        qs = qs.filter(privacy__in=Scene.WEB_READABLE_PRIVACY)
    rows = qs.values("room_id").annotate(count=Count("id")).values_list("room_id", "count")
    return dict(rows)


def recent_public_scene_ids_by_room(room_ids, *, limit=1):
    """
    ``{room_id: [scene_pk, ...]}`` — up to *limit* most recent closed,
    web-readable scenes per room, newest first.

    One query regardless of room count or limit: the ordered rows are walked
    once in Python, keeping the first *limit* seen per room. Public because a
    game building its own surface (a room page, a search index) needs the same
    answer; evennia_maps gets it through the overlay below and does not import
    this module.
    """
    if not room_ids:
        return {}
    rows = (
        Scene.objects.filter(
            room_id__in=room_ids,
            status=Scene.Status.CLOSED,
            privacy__in=Scene.WEB_READABLE_PRIVACY,
        )
        # -pk breaks ties: ended_at can be equal (or unset) across scenes.
        .order_by("room_id", "-ended_at", "-pk")
        .values_list("room_id", "pk")
    )
    result = {}
    for room_id, scene_pk in rows:
        bucket = result.setdefault(room_id, [])
        if len(bucket) < limit:
            bucket.append(scene_pk)
    return result


def _scene_labels_by_id(scene_ids):
    """
    ``{scene_pk: label}`` for the map popup's log links.

    ``Scene.title`` is optional, so fall back to the ``Scene #<pk>`` form
    ``Scene.__str__`` already uses rather than rendering a blank link.
    """
    if not scene_ids:
        return {}
    return {
        pk: title or f"Scene #{pk}"
        for pk, title in Scene.objects.filter(id__in=scene_ids).values_list("id", "title")
    }


def _recent_scenes_by_room(room_ids):
    recent = recent_public_scene_ids_by_room(room_ids, limit=_RECENT_LOG_LIMIT)
    labels = _scene_labels_by_id({pk for scene_ids in recent.values() for pk in scene_ids})
    return {
        room_id: [{"id": pk, "title": labels[pk]} for pk in scene_ids]
        for room_id, scene_ids in recent.items()
    }


def provide(sender, room_ids, staff, **kwargs):
    """
    ``collect_tile_overlays`` receiver — see the module docstring for the keys.

    Four queries for the whole grid, flat in tile count (three when no room
    in the request has a recent log to label). Never per tile: a 500-room
    plane renders in one request, and a per-tile lookup here would turn that
    into 500.
    """
    if not room_ids:
        return {}
    return {
        "has_active_scene": {rid: True for rid in _active_scene_room_ids(room_ids, staff=staff)},
        "recent_scene_count": _recent_scene_counts_by_room(room_ids, staff=staff),
        "recent_scenes": _recent_scenes_by_room(room_ids),
    }
