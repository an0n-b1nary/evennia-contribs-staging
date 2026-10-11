# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Plots -> Maps room panel: the plot threads that have touched this place.

evennia_maps asks its installed partners about one room when a player
clicks it on the live map, via the ``collect_tile_detail`` collector
signal, and this module answers with a ``plots`` section.

A thread touches a room through its scenes: a ``ScenePlotLink`` to a scene
held there. Plots don't record places themselves, so this needs
evennia_scenes too (``PLOTS_SCENES_APP_LABEL``, read through
``apps.get_model`` like plots' other scene wiring); without it the section
is simply absent.

Visibility, each part owned by its domain:

- **Scenes:** for players only scenes the web may show
  (``Scene.WEB_READABLE_PRIVACY``) count, so a private scene never
  reveals that a thread passed through a room. Staff count every scene.
- **Threads:** the same rule as plots' own pages. Private threads are left
  out for players; staff see them noted "private", unlinked, because the
  thread page doesn't serve them. Active and concluded threads are listed,
  newest first, up to ``MAX_THREADS``; proposed and archived ones are not.

Connected from PlotsConfig.ready(), gated on evennia_maps being installed
and new enough to have the seam.
"""

from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from evennia_plots.models import PlotThread, ScenePlotLink

MAX_THREADS = 10


def _scene_model():
    label = getattr(settings, "PLOTS_SCENES_APP_LABEL", "evennia_scenes")
    try:
        return apps.get_model(label, "Scene")
    except LookupError:
        return None


def _thread_url(pk):
    try:
        return reverse("evennia_plots:plot-detail", args=[pk])
    except NoReverseMatch:
        return ""


def provide_detail(sender, room_id, room, staff, **kwargs):
    """``collect_tile_detail`` receiver: the ``plots`` section. Three queries."""
    Scene = _scene_model()
    if Scene is None:
        return {}
    scenes = Scene.objects.filter(room_id=room_id)
    if not staff:
        scenes = scenes.filter(privacy__in=Scene.WEB_READABLE_PRIVACY)
    scene_ids = list(scenes.values_list("pk", flat=True))
    if not scene_ids:
        return {}
    thread_ids = (
        ScenePlotLink.objects.filter(scene_id__in=scene_ids)
        .values_list("thread_id", flat=True)
        .distinct()
    )
    threads = PlotThread.objects.filter(
        pk__in=thread_ids,
        status__in=[PlotThread.Status.ACTIVE, PlotThread.Status.CONCLUDED],
    ).select_related("arc")
    if not staff:
        threads = threads.exclude(privacy=PlotThread.Privacy.PRIVATE)
    threads = list(threads.order_by("status", "-pk")[:MAX_THREADS])
    if not threads:
        return {}
    items = []
    for thread in threads:
        private = thread.privacy == PlotThread.Privacy.PRIVATE
        notes = []
        if private:
            notes.append("private")
        if thread.status == PlotThread.Status.CONCLUDED:
            notes.append("concluded")
        if thread.arc_id:
            notes.append(f"part of {thread.arc.name}")
        items.append(
            {
                "label": thread.name,
                "url": "" if private else _thread_url(thread.pk),
                "note": ", ".join(notes),
            }
        )
    return {"plots": {"title": "Plots here", "order": 50, "items": items}}
