# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_lore XP integration — lore authoring and lore inspiration collectors.

This module ships the lore-domain XP feed. It is only active when registered
in the game's settings and evennia-xp is installed:

    XP_COLLECTORS += [
        ("lore_authored",    "evennia_lore.integrations.xp.collect_lore_authored"),
        ("lore_inspiration", "evennia_lore.integrations.xp.collect_lore_inspiration"),
    ]

Both functions import from evennia_xp at call time (not at module import), so
this file is safe to ship even when evennia-xp is not installed — it simply
can't be called meaningfully.

collect_lore_inspiration also performs optional cross-domain participant
discovery via evennia_rptracker (RPSession/RPSessionPartner). This is gated
at call time: if evennia_rptracker is not installed the collector falls back to
scene participants only. The scenes app label is configurable:

    LORE_SCENES_APP_LABEL = "scenes"  # default

The rptracker app is resolved via its standard installed-app label:

    LORE_RPTRACKER_APP_LABEL = "evennia_rptracker"  # default
"""

import logging
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger("evennia")

_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


# ---------------------------------------------------------------------------
# collect_lore_authored
# ---------------------------------------------------------------------------


def collect_lore_authored(window_end):
    """Yield Awards for published LoreEntries authored within the window.

    Uses LoreEntry.created_at as the publication timestamp — when
    LORE_REQUIRE_APPROVAL is False (the default) entries are published
    immediately on creation. When approval is required, entries sit in
    SUBMITTED status until staff publishes them; the created_at window
    still applies (conservative: only picks up entries created this week
    that are already published, not late-approved old entries).

    Skips entries that already have an XPLog row (LORE_AUTHORED, entry.pk)
    so re-runs are idempotent even without a flag field on LoreEntry.

    Args:
        window_end: datetime marking the end of the window.

    Yields:
        Award for each eligible LoreEntry.
    """
    from evennia_xp.batch import Award
    from evennia_xp.gating import resolve_xp_multiplier
    from evennia_xp.models import XPLog

    from evennia_lore.models import LoreEntry

    window_start = _window_start(window_end)
    entries = LoreEntry.objects.filter(
        status=LoreEntry.Status.PUBLISHED,
        created_at__gt=window_start,
        created_at__lte=window_end,
        author_id__isnull=False,
    )

    entry_ids = list(entries.values_list("pk", flat=True))
    if not entry_ids:
        return
    awarded_ids = set(
        XPLog.objects.filter(
            source_type=XPLog.SourceType.LORE_AUTHORED,
            source_ref_id__in=entry_ids,
        ).values_list("source_ref_id", flat=True)
    )

    for entry in entries:
        if entry.pk in awarded_ids:
            continue
        mult = resolve_xp_multiplier("lore")
        if not mult:
            continue
        yield Award(
            character_id=entry.author_id,
            amount=Decimal("1.0") * mult,
            source_type=XPLog.SourceType.LORE_AUTHORED,
            source_ref_id=entry.pk,
            multiplier=mult,
            reason=f"Lore authored: {entry.title}",
        )


# ---------------------------------------------------------------------------
# collect_lore_inspiration
# ---------------------------------------------------------------------------


def collect_lore_inspiration(window_end):
    """Yield Awards for each (LoreSceneLink, scene participant) pair in the window.

    For each LoreSceneLink created within the window, the scene's participants
    (excluding the lore author) each receive 0.5 XP. Participant discovery
    unions SceneParticipants and RPSession partners in the same scene's rooms.

    A LoreInspirationCredit bridge row is get_or_created for each
    (link, character_id) pair. Its pk is used as source_ref_id so that
    XPLog's (source_type, source_ref_id) uniqueness constraint guarantees
    idempotency across batch re-runs.

    The SceneParticipant model is resolved via LORE_SCENES_APP_LABEL
    (default: "scenes") to avoid a hard import on the scenes app.
    RPSession/RPSessionPartner are loaded only when evennia_rptracker is
    present in INSTALLED_APPS.

    Args:
        window_end: datetime marking the end of the window.

    Yields:
        Award per (link, participant) credit.
    """
    from django.apps import apps as django_apps
    from django.conf import settings
    from evennia_xp.batch import Award
    from evennia_xp.gating import resolve_xp_multiplier
    from evennia_xp.models import XPLog

    from evennia_lore.models import LoreInspirationCredit, LoreSceneLink

    window_start = _window_start(window_end)
    links = LoreSceneLink.objects.filter(
        created_at__gt=window_start,
        created_at__lte=window_end,
    ).select_related("entry")

    awarded_credit_ids = set(
        XPLog.objects.filter(
            source_type=XPLog.SourceType.LORE_INSPIRATION,
        ).values_list("source_ref_id", flat=True)
    )

    scenes_label = getattr(settings, "LORE_SCENES_APP_LABEL", "scenes")
    try:
        SceneParticipant = django_apps.get_model(scenes_label, "SceneParticipant")
    except Exception:
        logger.warning(
            "evennia_lore: scenes app %r not available; "
            "collect_lore_inspiration will use rptracker participants only.",
            scenes_label,
        )
        SceneParticipant = None

    rptracker_label = getattr(settings, "LORE_RPTRACKER_APP_LABEL", "evennia_rptracker")
    installed = {a.split(".")[-1] for a in settings.INSTALLED_APPS}
    use_rptracker = rptracker_label in installed
    if use_rptracker:
        try:
            from evennia_rptracker.models import RPSession, RPSessionPartner
        except ImportError:
            use_rptracker = False
            RPSession = RPSessionPartner = None
    else:
        RPSession = RPSessionPartner = None

    for link in links:
        author_id = link.entry.author_id

        scene_char_ids = set()
        if SceneParticipant is not None:
            scene_char_ids = set(
                SceneParticipant.objects.filter(scene_id=link.scene_id)
                .exclude(character_id__isnull=True)
                .values_list("character_id", flat=True)
            )

        partner_ids = set()
        if use_rptracker:
            session_ids_in_scene = list(
                RPSession.objects.filter(scene_links__scene_id=link.scene_id).values_list(
                    "pk", flat=True
                )
            )
            partner_ids = set(
                RPSessionPartner.objects.filter(session_id__in=session_ids_in_scene)
                .exclude(partner_id__isnull=True)
                .values_list("partner_id", flat=True)
            )

        participant_ids = (scene_char_ids | partner_ids) - {author_id} - {None}

        mult = resolve_xp_multiplier("lore")
        if not mult:
            continue

        for char_id in participant_ids:
            credit, _ = LoreInspirationCredit.objects.get_or_create(
                link=link,
                character_id=char_id,
            )
            if credit.pk in awarded_credit_ids:
                continue
            yield Award(
                character_id=char_id,
                amount=Decimal("0.5") * mult,
                source_type=XPLog.SourceType.LORE_INSPIRATION,
                source_ref_id=credit.pk,
                multiplier=mult,
                reason=f"Lore inspiration: {link.entry.title}",
            )
