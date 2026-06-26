# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Lottery and lifecycle scheduler for evennia_calendar.

All public functions are idempotent — re-running after a crash or missed
tick simply rechecks guard flags and no-ops if the work is already done.

Public API:
    run_lottery(event, rng=None)           — standalone staff event lottery
    run_cluster_lottery(cluster, rng=None) — cluster-wide ranked-choice draw
    expire_unconfirmed(event)              — release unconfirmed at 48h mark
    issue_post_event_tokens(event)         — issue tokens after event ends
    promote_waitlist(event, count=1)       — advance waitlist for capped events
    ensure_calendar_script_running()       — start maintenance Script if absent

CalendarMaintenanceScript (Evennia DefaultScript, 10-min interval) sweeps all
upcoming events and clusters whose deadline windows have passed and dispatches
the appropriate function. Started from at_server_start().

rng parameter: accepts a random.Random instance for deterministic testing.
If None, uses the module-level random functions (non-deterministic).
"""

import contextlib
import logging
import random as _random

logger = logging.getLogger("evennia")


# ---------------------------------------------------------------------------
# Standalone lottery
# ---------------------------------------------------------------------------


def run_lottery(event, rng=None):
    """
    Run the lottery draw for a standalone staff event.

    Idempotency: no-ops if event.lottery_drawn_at is already set.
    Only applicable to is_staff_event=True, non-clustered events.

    Draw order:
    1. Priority token holders (scope=EVENT, unredeemed) are seated first,
       consuming their tokens.
    2. Remaining LOTTERY_ENTERED pool is randomly sampled to fill remaining
       cap slots.
    3. Selected RSVPs → LOTTERY_SELECTED. Remaining stay LOTTERY_ENTERED.
    4. lottery_drawn_at set; lottery_drawn signal fired.

    Args:
        event: CalendarEvent instance with is_staff_event=True.
        rng: optional random.Random for deterministic testing.
    """
    from django.utils import timezone

    from evennia_calendar.models import RSVP, PriorityToken
    from evennia_calendar.signals import lottery_drawn, lottery_selected

    if event.lottery_drawn_at is not None:
        return  # idempotency guard

    if not event.is_staff_event:
        logger.warning(
            "Calendar: run_lottery called on non-staff event #%s. Skipping.",
            event.pk,
        )
        return

    if event.is_clustered:
        logger.warning(
            "Calendar: run_lottery called on clustered event #%s. "
            "Use run_cluster_lottery() for clustered events. Skipping.",
            event.pk,
        )
        return

    cap = event.participant_cap
    pool = list(event.rsvps.filter(status=RSVP.Status.LOTTERY_ENTERED).select_related("character"))

    selected = []

    # --- Priority token pre-seating ---
    if cap is not None:
        token_holders = []
        for rsvp in pool:
            if rsvp.character is None:
                continue
            token = PriorityToken.objects.filter(
                character=rsvp.character,
                scope=PriorityToken.Scope.EVENT,
                redeemed_at__isnull=True,
            ).first()
            if token:
                token_holders.append((rsvp, token))

        for rsvp, token in token_holders:
            if len(selected) >= cap:
                break
            token.redeemed_event = event
            token.redeemed_at = timezone.now()
            token.save(update_fields=["redeemed_event", "redeemed_at"])
            rsvp.status = RSVP.Status.LOTTERY_SELECTED
            rsvp.save(update_fields=["status", "updated_at"])
            selected.append(rsvp)
            pool.remove(rsvp)

    # --- Random draw for remaining slots ---
    slots_left = cap - len(selected) if cap is not None else len(pool)

    if slots_left > 0 and pool:
        rand = rng or _random
        winners = (
            rand.sample(pool, min(slots_left, len(pool))) if slots_left < len(pool) else pool[:]
        )
        for rsvp in winners:
            rsvp.status = RSVP.Status.LOTTERY_SELECTED
            rsvp.save(update_fields=["status", "updated_at"])
            selected.append(rsvp)

    # --- Persist draw timestamp ---
    event.lottery_drawn_at = timezone.now()
    event.save(update_fields=["lottery_drawn_at", "updated_at"])

    # --- Signals ---
    remaining_entered = event.rsvps.filter(status=RSVP.Status.LOTTERY_ENTERED).count()
    try:
        lottery_drawn.send(
            sender=event.__class__,
            event=event,
            selected=selected,
            lottery_entered_remaining=remaining_entered,
        )
    except Exception:
        logger.exception("Calendar: lottery_drawn signal failed for event #%s", event.pk)

    for rsvp in selected:
        try:
            lottery_selected.send(
                sender=rsvp.__class__,
                event=event,
                rsvp=rsvp,
            )
        except Exception:
            logger.exception("Calendar: lottery_selected signal failed for rsvp #%s", rsvp.pk)

    logger.info(
        "Calendar: lottery drawn for event #%s '%s'. " "Selected %d, remaining in pool %d.",
        event.pk,
        event.title,
        len(selected),
        remaining_entered,
    )


# ---------------------------------------------------------------------------
# Cluster lottery
# ---------------------------------------------------------------------------


def run_cluster_lottery(cluster, rng=None):
    """
    Run the ranked-choice lottery for an EventCluster.

    Idempotency: no-ops if cluster.has_run is True (any member event has
    lottery_drawn_at set).

    Requires cluster.is_locked=True (prevents draws on in-progress clusters).

    Algorithm:
    1. Token pre-seating: ClusterRSVP holders with a CLUSTER_RANK1 token for
       this cluster are seated in their rank-1 event if capacity allows.
       If rank-1 is full from other token holders, seat at rank-2 and issue
       a fresh CLUSTER_RANK1 token (preserves the guarantee).
    2. Random draw: remaining PENDING ClusterRSVPs are shuffled and each
       player is placed in the highest-ranked event with seats_remaining > 0.
    3. Unseated: players whose ranked events are all full get status=UNSEATED
       and a CLUSTER_RANK1 token.
       Players seated below rank-1 also get a CLUSTER_RANK1 token (they didn't
       get their top choice; the token makes them whole next time).
    4. Concrete RSVP rows (status=LOTTERY_SELECTED) created for seated players.
    5. lottery_drawn_at set on all member events; signals fired.

    Args:
        cluster: EventCluster instance with is_locked=True.
        rng: optional random.Random for deterministic testing.
    """
    from django.utils import timezone

    from evennia_calendar.models import RSVP, ClusterRSVP, PriorityToken
    from evennia_calendar.signals import cluster_drawn, cluster_seat_assigned

    if cluster.has_run:
        return  # idempotency guard

    if not cluster.is_locked:
        logger.warning(
            "Calendar: run_cluster_lottery called on unlocked cluster #%s. " "Skipping.",
            cluster.pk,
        )
        return

    # Build per-event capacity tracker (live seats_remaining).
    events = list(cluster.events.filter(is_cancelled=False))
    seats = {}
    for ev in events:
        seats[ev.pk] = ev.seats_remaining  # None = unlimited

    def has_capacity(ev):
        s = seats[ev.pk]
        return s is None or s > 0

    def consume_seat(ev):
        if seats[ev.pk] is not None:
            seats[ev.pk] -= 1

    def get_token_for(character):
        """Find an unredeemed CLUSTER_RANK1 token for this cluster."""
        return PriorityToken.objects.filter(
            character=character,
            scope=PriorityToken.Scope.CLUSTER_RANK1,
            source_cluster=cluster,
            redeemed_at__isnull=True,
        ).first()

    pending = list(
        ClusterRSVP.objects.filter(
            cluster=cluster, status=ClusterRSVP.Status.PENDING
        ).select_related("character")
    )

    # Map ClusterRSVP pk → ordered preference list (CalendarEvent objects).
    preferences_map = {}
    for crsvp in pending:
        prefs = list(crsvp.get_ordered_preferences())
        preferences_map[crsvp.pk] = [p.event for p in prefs]

    seated_rsvps = []  # (ClusterRSVP, CalendarEvent, rank_achieved)
    unseated_rsvps = []
    # crsvp.pk set: these already received a replacement CLUSTER_RANK1 token
    # in step 1 and should NOT receive another in step 3.
    token_reissued_pks = set()

    token_holders = [crsvp for crsvp in pending if get_token_for(crsvp.character) is not None]
    non_token_holders = [crsvp for crsvp in pending if crsvp not in token_holders]

    # --- Step 1: Token pre-seating ---
    for crsvp in token_holders:
        token = get_token_for(crsvp.character)
        prefs = preferences_map.get(crsvp.pk, [])
        seated_event = None
        rank_achieved = None

        # Try rank-1 first (what the token guarantees).
        if prefs and has_capacity(prefs[0]):
            seated_event = prefs[0]
            rank_achieved = 1
        else:
            # rank-1 full; fall through to best available.
            for idx, ev in enumerate(prefs, start=1):
                if has_capacity(ev):
                    seated_event = ev
                    rank_achieved = idx
                    break

        # Consume token.
        token.redeemed_cluster = cluster
        token.redeemed_at = timezone.now()
        token.save(update_fields=["redeemed_cluster", "redeemed_at"])

        if seated_event:
            consume_seat(seated_event)
            seated_rsvps.append((crsvp, seated_event, rank_achieved))
            # If not rank-1, issue a fresh token (rank-1 was unavailable).
            if rank_achieved != 1:
                PriorityToken.objects.create(
                    character=crsvp.character,
                    character_name=crsvp.character_name,
                    source_cluster=cluster,
                    scope=PriorityToken.Scope.CLUSTER_RANK1,
                )
                token_reissued_pks.add(crsvp.pk)
        else:
            unseated_rsvps.append(crsvp)
            # Token was consumed but player got nothing; issue a fresh one.
            PriorityToken.objects.create(
                character=crsvp.character,
                character_name=crsvp.character_name,
                source_cluster=cluster,
                scope=PriorityToken.Scope.CLUSTER_RANK1,
            )
            token_reissued_pks.add(crsvp.pk)

    # --- Step 2: Random draw for remaining players ---
    rand = rng or _random
    rand.shuffle(non_token_holders)

    for crsvp in non_token_holders:
        prefs = preferences_map.get(crsvp.pk, [])
        seated_event = None
        rank_achieved = None

        for idx, ev in enumerate(prefs, start=1):
            if has_capacity(ev):
                seated_event = ev
                rank_achieved = idx
                break

        if seated_event:
            consume_seat(seated_event)
            seated_rsvps.append((crsvp, seated_event, rank_achieved))
        else:
            unseated_rsvps.append(crsvp)

    # --- Step 3: Issue tokens and update statuses ---
    now = timezone.now()

    for crsvp, ev, rank in seated_rsvps:
        # Create concrete RSVP.
        rsvp = RSVP.objects.create(
            event=ev,
            character=crsvp.character,
            character_name=crsvp.character_name,
            status=RSVP.Status.LOTTERY_SELECTED,
            cluster_rsvp=crsvp,
        )
        crsvp.status = ClusterRSVP.Status.SEATED
        crsvp.save(update_fields=["status", "updated_at"])

        # Players seated below rank-1 also get a token (didn't get top choice).
        # Skip if step 1 already issued a replacement token for this crsvp
        # (token holder seated at rank-2+).
        if rank != 1 and crsvp.pk not in token_reissued_pks:
            PriorityToken.objects.create(
                character=crsvp.character,
                character_name=crsvp.character_name,
                source_cluster=cluster,
                scope=PriorityToken.Scope.CLUSTER_RANK1,
            )

        try:
            cluster_seat_assigned.send(
                sender=ClusterRSVP,
                cluster=cluster,
                cluster_rsvp=crsvp,
                rsvp=rsvp,
                rank_achieved=rank,
            )
        except Exception:
            logger.exception(
                "Calendar: cluster_seat_assigned signal failed for ClusterRSVP #%s",
                crsvp.pk,
            )

    for crsvp in unseated_rsvps:
        crsvp.status = ClusterRSVP.Status.UNSEATED
        crsvp.save(update_fields=["status", "updated_at"])
        # Token already issued in step 1 for token holders who got nothing;
        # issue for non-token unseated players here.
        if crsvp.pk not in token_reissued_pks:
            PriorityToken.objects.create(
                character=crsvp.character,
                character_name=crsvp.character_name,
                source_cluster=cluster,
                scope=PriorityToken.Scope.CLUSTER_RANK1,
            )

    # --- Step 4: Mark all member events as drawn ---
    for ev in events:
        ev.lottery_drawn_at = now
        ev.save(update_fields=["lottery_drawn_at", "updated_at"])

    # --- Step 5: Fire cluster_drawn signal ---
    try:
        cluster_drawn.send(
            sender=cluster.__class__,
            cluster=cluster,
            seated_count=len(seated_rsvps),
            unseated_count=len(unseated_rsvps),
        )
    except Exception:
        logger.exception("Calendar: cluster_drawn signal failed for cluster #%s", cluster.pk)

    logger.info(
        "Calendar: cluster draw complete for cluster #%s '%s'. " "Seated %d, unseated %d.",
        cluster.pk,
        cluster.title,
        len(seated_rsvps),
        len(unseated_rsvps),
    )


# ---------------------------------------------------------------------------
# Expiry and backfill
# ---------------------------------------------------------------------------


def expire_unconfirmed(event):
    """
    Release LOTTERY_SELECTED and INVITED RSVPs that missed the 48h deadline.

    Idempotent — running again after a partial failure just re-checks.
    For standalone staff events, triggers backfill from the remaining pool.
    For clustered events, backfill pulls from the cluster's UNSEATED pool first.

    Args:
        event: CalendarEvent instance.
    """
    from evennia_calendar.models import RSVP, ClusterRSVP
    from evennia_calendar.signals import lottery_confirmation_expired

    expirable = event.rsvps.filter(status__in=[RSVP.Status.LOTTERY_SELECTED, RSVP.Status.INVITED])
    released = []
    for rsvp in expirable:
        rsvp.release()
        released.append(rsvp)
        try:
            lottery_confirmation_expired.send(sender=rsvp.__class__, event=event, rsvp=rsvp)
        except Exception:
            logger.exception(
                "Calendar: lottery_confirmation_expired signal failed for rsvp #%s",
                rsvp.pk,
            )

    if not released:
        return

    # --- Backfill ---
    if event.is_clustered and event.cluster:
        # Pull from cluster's UNSEATED pool (players who wanted in).
        unseated_cluster_rsvps = ClusterRSVP.objects.filter(
            cluster=event.cluster,
            status=ClusterRSVP.Status.UNSEATED,
        ).order_by("created_at")[: len(released)]

        for crsvp in unseated_cluster_rsvps:
            RSVP.objects.create(
                event=event,
                character=crsvp.character,
                character_name=crsvp.character_name,
                status=RSVP.Status.LOTTERY_SELECTED,
                cluster_rsvp=crsvp,
            )
            crsvp.status = ClusterRSVP.Status.SEATED
            crsvp.save(update_fields=["status", "updated_at"])
    elif event.is_staff_event:
        # Standalone: draw from remaining LOTTERY_ENTERED pool.
        remaining = list(event.rsvps.filter(status=RSVP.Status.LOTTERY_ENTERED)[: len(released)])
        for rsvp in remaining:
            rsvp.status = RSVP.Status.LOTTERY_SELECTED
            rsvp.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# Post-event token issuance
# ---------------------------------------------------------------------------


def issue_post_event_tokens(event):
    """
    Issue PriorityTokens to players who entered but were never selected.

    Only applicable to standalone staff events (clustered events issue tokens
    at draw time in run_cluster_lottery, so this is a no-op for them).

    Safe to call multiple times — checks that the event is past and that
    LOTTERY_ENTERED RSVPs still exist before creating tokens.

    Args:
        event: CalendarEvent instance with is_staff_event=True.
    """
    from evennia_calendar.models import RSVP, PriorityToken

    if event.is_clustered:
        return  # tokens issued at draw time for clusters

    if not event.is_staff_event:
        return

    entered = event.rsvps.filter(status=RSVP.Status.LOTTERY_ENTERED).select_related("character")
    for rsvp in entered:
        if rsvp.character is None:
            continue
        PriorityToken.objects.create(
            character=rsvp.character,
            character_name=rsvp.character_name,
            source_event=event,
            scope=PriorityToken.Scope.EVENT,
        )

    count = entered.count()
    if count:
        logger.info(
            "Calendar: issued %d priority token(s) after event #%s '%s'.",
            count,
            event.pk,
            event.title,
        )


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------


def promote_waitlist(event, count=1):
    """
    Promote the next N waitlisted RSVPs to CONFIRMED.

    Used by +rsvp/ping (host manual promotion) and by expire_unconfirmed
    backfill for capped non-staff events.

    Args:
        event: CalendarEvent instance.
        count: number of waitlist slots to fill (default 1).
    """
    from evennia_calendar.models import RSVP
    from evennia_calendar.signals import waitlist_promoted

    promoted = event.rsvps.filter(status=RSVP.Status.WAITLISTED).order_by(
        "waitlist_position", "created_at"
    )[:count]

    for rsvp in promoted:
        rsvp.confirm()
        try:
            waitlist_promoted.send(sender=rsvp.__class__, event=event, rsvp=rsvp)
        except Exception:
            logger.exception(
                "Calendar: waitlist_promoted signal failed for rsvp #%s",
                rsvp.pk,
            )


# ---------------------------------------------------------------------------
# Maintenance sweep
# ---------------------------------------------------------------------------


def _sweep_events():
    """
    Called by CalendarMaintenanceScript every 10 minutes.

    Checks all upcoming (non-cancelled) events and clusters:
    - Standalone staff events: run_lottery() when past lottery_draw_time
      and lottery_drawn_at is null.
    - Clusters: run_cluster_lottery() when past draw_time and not has_run.
    - All events: expire_unconfirmed() when past confirmation_deadline.
    - All past staff events: issue_post_event_tokens() when past
      scheduled_time.
    - 24h reminder signal for events starting within the next 25 minutes
      (10min sweep interval + 15min buffer).
    """
    from datetime import timedelta

    from django.utils import timezone

    from evennia_calendar.models import CalendarEvent, EventCluster
    from evennia_calendar.signals import event_starting_soon

    now = timezone.now()

    # --- Cluster draws ---
    for cluster in EventCluster.objects.filter(is_locked=True):
        if cluster.has_run:
            continue
        draw_time = cluster.draw_time
        if draw_time and now >= draw_time:
            try:
                run_cluster_lottery(cluster)
            except Exception:
                logger.exception("Calendar: cluster draw failed for cluster #%s", cluster.pk)

    # --- Standalone event draws and lifecycle ---
    upcoming = CalendarEvent.objects.filter(
        is_cancelled=False,
        scheduled_time__gte=now - timedelta(days=1),
    )
    for event in upcoming:
        try:
            # Lottery draw (72h before)
            if (
                event.is_staff_event
                and not event.is_clustered
                and event.lottery_drawn_at is None
                and event.lottery_draw_time
                and now >= event.lottery_draw_time
            ):
                run_lottery(event)

            # Expire unconfirmed (48h before)
            if now >= event.confirmation_deadline:
                expire_unconfirmed(event)

            # Post-event tokens
            if event.is_past:
                issue_post_event_tokens(event)

            # 24h reminder
            reminder_window = timedelta(hours=24)
            buffer = timedelta(minutes=25)
            time_until = event.scheduled_time - now
            if timedelta(0) <= time_until <= reminder_window + buffer:
                with contextlib.suppress(Exception):
                    event_starting_soon.send(sender=event.__class__, event=event)

        except Exception:
            logger.exception("Calendar: sweep error for event #%s", event.pk)


# ---------------------------------------------------------------------------
# Evennia Script
# ---------------------------------------------------------------------------


def ensure_calendar_script_running():
    """
    Create CalendarMaintenanceScript if it is not already running.

    Call this from your game's at_server_start() hook. Safe to call multiple
    times — the script is persistent and survives server reboots once created.

    Example::

        # server/conf/at_server_startstop.py
        from evennia_calendar.scheduler import ensure_calendar_script_running

        def at_server_start():
            ensure_calendar_script_running()

    There is no Evennia server-start signal, so this must be called manually.
    """
    from evennia.utils.search import search_script

    existing = search_script("calendar_maintenance")
    if not existing:
        from evennia.utils.create import create_script

        create_script(
            "evennia_calendar.scheduler.CalendarMaintenanceScript",
            key="calendar_maintenance",
            persistent=True,
            autostart=True,
        )
        logger.info("Calendar: maintenance Script started.")


try:
    from evennia import DefaultScript

    class CalendarMaintenanceScript(DefaultScript):
        """
        Evennia Script that periodically runs calendar lifecycle tasks.

        Runs every 10 minutes. Dispatches lottery draws, expires unconfirmed
        RSVPs, issues post-event tokens, and fires 24h reminder signals.
        """

        def at_script_creation(self):
            self.key = "calendar_maintenance"
            self.desc = "Runs calendar lottery draws and RSVP lifecycle (every 10 min)."
            self.interval = 600  # 10 minutes
            self.persistent = True

        def at_repeat(self):
            _sweep_events()

except ImportError:
    # Running outside Evennia (e.g. plain Django manage.py shell).
    # CalendarMaintenanceScript is unavailable but all module-level
    # functions remain usable.
    pass
