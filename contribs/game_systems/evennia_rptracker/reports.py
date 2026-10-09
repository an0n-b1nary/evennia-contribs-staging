# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Read-only activity aggregates; room geography and global channels stay separate."""

from collections import defaultdict
from contextlib import suppress
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def activity_report(days=7, *, now=None):
    """Return aggregate rows for activated sessions overlapping a rolling window.

    Region attribution uses current memberships. Account totals count known
    snapshots only; deleted/legacy participants with no snapshot stay unknown.
    Minutes are participant-minutes, not wall time or an effort score.
    """
    from evennia_rptracker.channel_tracker import _active_channel_sessions
    from evennia_rptracker.models import RPSession

    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("Choose 1 to 90 days.")
    now = now or timezone.now()
    start = now - timedelta(days=days)
    label = getattr(settings, "RPTRACKER_REGIONS_APP_LABEL", "evennia_regions")
    regions = None
    if apps.is_installed(label) or any(c.label == label for c in apps.get_app_configs()):
        with suppress(LookupError):
            regions = apps.get_model(label, "RegionMembership")
    sessions = (
        RPSession.objects.filter(
            activated_at__lt=now,
        )
        .filter(Q(ended_at__gt=start) | Q(status=RPSession.Status.ACTIVE))
        .select_related("room")
    )
    groups = defaultdict(
        lambda: {
            "active": 0,
            "completed": 0,
            "flagged": 0,
            "characters": set(),
            "accounts": set(),
            "unknown_accounts": set(),
            "minutes": 0.0,
        }
    )
    room_groups = {}
    live = {s["session_id"]: s for s in _active_channel_sessions.values() if s["session_id"]}
    for session in sessions:
        if session.source_type == RPSession.Source.CHANNEL:
            key = (
                "channel",
                session.channel_id or session.channel_name,
                session.channel_name or "Deleted channel",
            )
            end = session.last_activity_at or session.activated_at
            if session.pk in live:
                from datetime import UTC, datetime

                end = datetime.fromtimestamp(live[session.pk]["last_activity"], tz=UTC)
        elif session.room_id is None:
            # A deleted room keeps its own snapshot name, never a shared cache slot.
            key = ("room", None, f"{session.room_name or 'Unnamed room'} (deleted)")
            end = session.ended_at or now
        else:
            if session.room_id not in room_groups:
                if regions:
                    membership = regions.primary_for(session.room_id)
                    room_groups[session.room_id] = (
                        ("region", membership.region_id, membership.region.name)
                        if membership
                        else ("region", None, "Unassigned rooms")
                    )
                else:
                    room_groups[session.room_id] = (
                        "room",
                        session.room_id,
                        session.room_name or "Deleted room",
                    )
            key = room_groups[session.room_id]
            end = session.ended_at or now
        seconds = max(0, (min(end, now) - max(session.activated_at, start)).total_seconds())
        if end <= start:
            continue
        group = groups[key]
        if session.status == RPSession.Status.FLAGGED:
            group["flagged"] += 1
            continue
        if session.status not in (RPSession.Status.ACTIVE, RPSession.Status.COMPLETED):
            continue
        group[session.status] += 1
        # Deleted characters still participated; identify them by snapshot name.
        participant = session.character_id or ("deleted", session.character_name)
        group["characters"].add(participant)
        if session.account_id_snapshot:
            group["accounts"].add(session.account_id_snapshot)
        else:
            group["unknown_accounts"].add(participant)
        group["minutes"] += seconds / 60
    rows = []
    for (kind, identity, name), group in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][2].casefold())
    ):
        rows.append(
            {
                "kind": kind,
                "id": identity,
                "name": name,
                **{k: len(v) if isinstance(v, set) else v for k, v in group.items()},
            }
        )
    return {"start": start, "end": now, "rows": rows, "regions": regions is not None}
