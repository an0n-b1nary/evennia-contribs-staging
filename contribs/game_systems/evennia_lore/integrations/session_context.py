# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Shipped ``LORE_SESSION_CONTEXT_PROVIDER``: room, region and plot threads.

The passive trickle weights entries by where and in what story a finished
RP session happened. This provider answers that from the sibling contribs::

    # settings.py
    LORE_SESSION_CONTEXT_PROVIDER = (
        "evennia_lore.integrations.session_context.get_session_context"
    )

* ``room_id``: the session's room.
* ``region_id``: the room's primary region (``RegionMembership.primary_for``)
  from the app at ``LORE_REGIONS_APP_LABEL``.
* ``thread_ids``: plot threads linked to any scene the session overlapped:
  the session's ``scene_links`` (evennia-rptracker's ``RPSessionSceneLink``),
  then ``ScenePlotLink`` from the app at ``LORE_PLOTS_APP_LABEL``.

Each partner is optional and located through the app registry, so nothing is
imported from an app that is absent: no regions app means ``region_id`` is
None, no plots app means no threads. A failure resolving one part is logged
and leaves the other parts intact.
"""

import logging

from django.apps import apps
from django.conf import settings

logger = logging.getLogger("evennia")


def _partner_model(setting, default_label, model_name):
    """The model from the partner app named by *setting*, or None if absent."""
    label = getattr(settings, setting, default_label)
    if not (apps.is_installed(label) or any(cfg.label == label for cfg in apps.get_app_configs())):
        return None
    try:
        return apps.get_model(label, model_name)
    except LookupError:
        return None


def _region_id(room_id):
    if room_id is None:
        return None
    membership_model = _partner_model(
        "LORE_REGIONS_APP_LABEL", "evennia_regions", "RegionMembership"
    )
    if membership_model is None:
        return None
    membership = membership_model.primary_for(room_id)
    return membership.region_id if membership else None


def _thread_ids(session):
    scene_links = getattr(session, "scene_links", None)
    if scene_links is None:
        return set()
    scene_ids = set(scene_links.values_list("scene_id", flat=True))
    if not scene_ids:
        return set()
    link_model = _partner_model("LORE_PLOTS_APP_LABEL", "evennia_plots", "ScenePlotLink")
    if link_model is None:
        return set()
    return set(
        link_model.objects.filter(scene_id__in=scene_ids).values_list("thread_id", flat=True)
    )


def get_session_context(session):
    """Return ``{"room_id", "region_id", "thread_ids"}`` for a finished RPSession.

    Args:
        session: an evennia-rptracker ``RPSession``.
    """
    room_id = getattr(session, "room_id", None)
    region_id = None
    thread_ids = set()
    try:
        region_id = _region_id(room_id)
    except Exception:
        logger.exception("lore session context: region lookup failed for room #%s", room_id)
    try:
        thread_ids = _thread_ids(session)
    except Exception:
        logger.exception(
            "lore session context: thread lookup failed for session #%s",
            getattr(session, "pk", None),
        )
    return {"room_id": room_id, "region_id": region_id, "thread_ids": thread_ids}
