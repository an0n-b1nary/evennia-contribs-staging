# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Passive lore trickle algorithm for evennia_lore.

When an RPSession ends (via the rptracker contrib), select_passive_lore(character, session)
is called to determine which lore entry (if any) the character passively acquires.

Algorithm:
1.  Build the eligible pool: PUBLISHED, PUBLIC, non-archived entries the
    character does not already own.
2.  Assign integer weights based on contextual relevance:
        plot-thread linked (via PlotLoreLink)         — 8
        room directly associated (entry.rooms)        — 5
        region linked (via LoreRegionLink)            — 3
        major-tag match                               — 2
        any tag match                                 — 1
    Weights are additive. An entry with no signal gets weight 0 and is
    excluded from the draw.
3.  Apply the lean multiplier: multiply an entry's weight by
    settings.LORE_PASSIVE_LEAN_MULTIPLIER when the entry matches the
    character's lore lean (lore_lean_type / lore_lean_value).
4.  Enforce the weekly ceiling: if the character has already acquired
    settings.LORE_PASSIVE_WEEKLY_CEILING entries via PASSIVE source this
    week, return None immediately.
5.  Weighted-random draw: pick one entry proportionally to its weight.
6.  Record acquisition: create a LoreAcquisition(source=PASSIVE) row and
    fire the lore_acquired signal.

Cross-domain context (room_id / region_id / thread_ids) is supplied by the
callable at settings.LORE_SESSION_CONTEXT_PROVIDER. When absent the engine
degrades gracefully to tag-only weighting.

Provider contract:
    def provider(session) -> dict:
        return {
            "room_id": int | None,   # ObjectDB pk of the session's room
            "region_id": int | None, # Region pk containing the room
            "thread_ids": set[int],  # PlotThread pks active during the session
        }

_build_pool(character, session) → list of (LoreEntry, weight) pairs is
exposed so tests can verify pool composition without mocking random.
"""

import random
from decimal import Decimal
from importlib import import_module

from django.conf import settings
from django.utils import timezone


def _resolve_context(session):
    """Call LORE_SESSION_CONTEXT_PROVIDER to obtain cross-domain session context.

    Returns a dict with keys ``room_id``, ``region_id``, ``thread_ids``.
    Returns empty context when the setting is absent or the provider raises,
    so the trickle degrades to tag-only weighting rather than breaking.
    """
    provider_path = getattr(settings, "LORE_SESSION_CONTEXT_PROVIDER", None)
    if not provider_path:
        return {"room_id": None, "region_id": None, "thread_ids": set()}
    try:
        module_path, func_name = provider_path.rsplit(".", 1)
        provider = getattr(import_module(module_path), func_name)
        return provider(session)
    except Exception:
        return {"room_id": None, "region_id": None, "thread_ids": set()}


def _lean_matches(entry, lean_type, lean_value):
    """Return True if the entry matches the character's lore lean."""
    if lean_type is None or lean_value is None:
        return False
    if lean_type == "tag":
        return entry.tags.filter(name__iexact=lean_value).exists()
    if lean_type == "region":
        from evennia_lore.models import LoreRegionLink

        try:
            # lean_value stores the region name; resolve to pk for the bridge query.
            # Attempt direct integer lookup first (robust if caller stored pk).
            try:
                region_pk = int(lean_value)
            except (ValueError, TypeError):
                # Resolve by name via the regions app if present.
                from django.apps import apps as _apps
                from django.conf import settings as _s

                regions_label = getattr(_s, "LORE_REGIONS_APP_LABEL", "evennia_regions")
                Region = _apps.get_model(regions_label, "Region")
                region = Region.objects.filter(name__iexact=lean_value).first()
                if region is None:
                    return False
                region_pk = region.pk
            return LoreRegionLink.objects.filter(entry=entry, region_id=region_pk).exists()
        except Exception:
            return False
    if lean_type == "entry":
        try:
            return entry.entry_number == int(lean_value)
        except (ValueError, TypeError):
            return False
    if lean_type == "theme":
        return entry.tags.filter(name__icontains=lean_value, is_major=True).exists()
    if lean_type == "plot":
        from evennia_lore.models import PlotLoreLink

        try:
            from django.apps import apps as _apps
            from django.conf import settings as _s

            plots_label = getattr(_s, "LORE_PLOTS_APP_LABEL", "evennia_plots")
            PlotThread = _apps.get_model(plots_label, "PlotThread")
            thread_ids = PlotThread.objects.filter(plot__title__icontains=lean_value).values_list(
                "id", flat=True
            )
            return PlotLoreLink.objects.filter(entry=entry, thread_id__in=thread_ids).exists()
        except Exception:
            return False
    return False


def _build_pool(character, session):
    """
    Build the weighted candidate pool for passive lore selection.

    Args:
        character: ObjectDB Character typeclass instance.
        session: RPSession instance (completed).

    Returns:
        list of (LoreEntry, int) tuples, weight > 0, sorted descending by weight.
    """
    from evennia_lore.models import LoreAcquisition, LoreEntry, LoreRegionLink, PlotLoreLink

    owned_pks = set(
        LoreAcquisition.objects.filter(character=character).values_list("entry_id", flat=True)
    )

    eligible = (
        LoreEntry.objects.filter(
            status=LoreEntry.Status.PUBLISHED,
            privacy=LoreEntry.Privacy.PUBLIC,
            is_archived=False,
        )
        .exclude(pk__in=owned_pks)
        .prefetch_related("tags", "rooms")
    )

    ctx = _resolve_context(session)
    room_id = ctx.get("room_id")
    region_id = ctx.get("region_id")
    thread_ids = ctx.get("thread_ids") or set()

    plot_linked_pks = set()
    if thread_ids:
        plot_linked_pks = set(
            PlotLoreLink.objects.filter(thread_id__in=thread_ids).values_list("entry_id", flat=True)
        )

    region_linked_pks = set()
    if region_id:
        region_linked_pks = set(
            LoreRegionLink.objects.filter(region_id=region_id).values_list("entry_id", flat=True)
        )

    lean_type = getattr(character, "lore_lean_type", None)
    lean_value = getattr(character, "lore_lean_value", None)
    lean_mult = getattr(settings, "LORE_PASSIVE_LEAN_MULTIPLIER", Decimal("2.0"))

    pool = []
    for entry in eligible:
        weight = 0

        if entry.pk in plot_linked_pks:
            weight += 8
        if room_id and entry.rooms.filter(pk=room_id).exists():
            weight += 5
        if entry.pk in region_linked_pks:
            weight += 3

        entry_tags = list(entry.tags.all())
        if any(t.is_major for t in entry_tags):
            weight += 2
        elif entry_tags:
            weight += 1

        if weight == 0:
            continue

        if _lean_matches(entry, lean_type, lean_value):
            weight = int(Decimal(str(weight)) * lean_mult)

        pool.append((entry, weight))

    pool.sort(key=lambda x: x[1], reverse=True)
    return pool


def _weekly_passive_count(character):
    """Return how many PASSIVE acquisitions this character has this week."""
    from evennia_lore.models import LoreAcquisition

    now = timezone.now()
    week_start = now - timezone.timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    return LoreAcquisition.objects.filter(
        character=character,
        source=LoreAcquisition.Source.PASSIVE,
        acquired_at__gte=week_start,
    ).count()


def select_passive_lore(character, session):
    """
    Select and record a passive lore acquisition for character after a session.

    Args:
        character: ObjectDB Character typeclass instance (session owner).
        session: RPSession instance (just completed).

    Returns:
        LoreEntry if an entry was acquired, else None.
    """
    from evennia_lore.models import LoreAcquisition
    from evennia_lore.signals import lore_acquired

    ceiling = getattr(settings, "LORE_PASSIVE_WEEKLY_CEILING", 5)
    if _weekly_passive_count(character) >= ceiling:
        return None

    pool = _build_pool(character, session)
    if not pool:
        return None

    entries, weights = zip(*pool, strict=False)
    (chosen,) = random.choices(entries, weights=weights, k=1)

    acquisition, created = LoreAcquisition.objects.get_or_create(
        entry=chosen,
        character=character,
        defaults={
            "character_name": character.key,
            "source": LoreAcquisition.Source.PASSIVE,
            "session_id": session.pk if session is not None else None,
        },
    )
    if not created:
        return None

    lore_acquired.send(
        sender=LoreAcquisition,
        acquisition=acquisition,
        character=character,
        entry=chosen,
    )
    return chosen
