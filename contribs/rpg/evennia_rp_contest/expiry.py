# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public expiry hooks for a game, optional partners and an idle sweep."""

from django.utils import timezone

from evennia_rp_contest import conf
from evennia_rp_contest.models import Challenge
from evennia_rp_contest.services import close_challenge


def _close(queryset, reason):
    return sum(close_challenge(challenge, reason=reason) for challenge in queryset)


def sweep_idle(*, room=None, now=None):
    """Close idle challenges. Commands sweep lazily; games may schedule this API."""
    ttl = conf.idle_ttl()
    if ttl is None:
        return 0
    cutoff = (now or timezone.now()) - ttl
    queryset = Challenge.objects.filter(
        status=Challenge.Status.OPEN,
        last_activity__lte=cutoff,
    )
    if room is not None:
        queryset = queryset.filter(room=room)
    return sum(close_challenge(c, reason="idle", idle_before=cutoff) for c in queryset)


def close_for_setter(character):
    return _close(
        Challenge.objects.filter(set_by=character, status=Challenge.Status.OPEN), "session_end"
    )


def close_for_scene(scene_id):
    return _close(
        Challenge.objects.filter(scene_id=scene_id, status=Challenge.Status.OPEN), "scene_closed"
    )
