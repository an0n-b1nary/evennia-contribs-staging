# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_calendar — event calendar system for Evennia games.

Public API (model classes are loaded lazily to avoid AppRegistryNotReady
when this package is imported during Django's app-loading phase):

    EventTag              — reusable thematic tag (staff-managed)
    EventCluster          — grouped events for ranked-choice RSVP
    CalendarEvent         — a scheduled event (open / capped / lottery modes)
    ClusterRSVP           — a player's ranked-choice ticket for a cluster
    ClusterRSVPPreference — through-model for ordered cluster event preferences
    RSVP                  — a player's concrete attendance record for an event
    PriorityToken         — lottery consolation guarantee (EVENT / CLUSTER_RANK1)
    EventExclusion        — mutual-exclusion pair for standalone events

    Emphasis      — CalendarEvent.Emphasis (COMBAT / SKILL / SOCIAL / FREEFORM)
    ClusterStatus — ClusterRSVP.Status (PENDING / SEATED / UNSEATED)
    RSVPStatus    — RSVP.Status (CONFIRMED / WAITLISTED / INVITED / …)
    TokenScope    — PriorityToken.Scope (EVENT / CLUSTER_RANK1)

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    event_created, event_cancelled, event_starting_soon,
    lottery_drawn, lottery_selected, lottery_confirmation_expired,
    rsvp_status_changed, waitlist_promoted,
    cluster_drawn, cluster_seat_assigned

Commands (import explicitly when needed):

    from evennia_calendar.commands import CmdCalendar, CmdRsvp

Scheduler (import explicitly when needed):

    from evennia_calendar.scheduler import (
        run_lottery, run_cluster_lottery, expire_unconfirmed,
        issue_post_event_tokens, promote_waitlist,
        ensure_calendar_script_running,
    )

Web/API surface (requires [web] extra):

    from evennia_calendar.views import CalendarMonthView, CalendarEventDetailView
    # wire URLs with: include(("evennia_calendar.urls", "evennia_calendar"))
    # API: include("evennia_calendar.api.urls") at /api/v1/ or similar

Integration contract — IMPORTANT:

    Call ensure_calendar_script_running() from your at_server_start() hook:

        from evennia_calendar.scheduler import ensure_calendar_script_running

        def at_server_start():
            ensure_calendar_script_running()

    There is no Evennia server-start signal, so the maintenance script that
    runs lottery draws, RSVP expiry, token issuance, and 24h reminders must
    be started manually. The script is persistent (survives reboots once
    started). See README for details.
"""

__version__ = "0.1.0"

from evennia_calendar.signals import (
    cluster_drawn,
    cluster_seat_assigned,
    event_cancelled,
    event_created,
    event_starting_soon,
    lottery_confirmation_expired,
    lottery_drawn,
    lottery_selected,
    rsvp_status_changed,
    waitlist_promoted,
)

_LAZY = {
    "EventTag": "models",
    "EventCluster": "models",
    "CalendarEvent": "models",
    "ClusterRSVP": "models",
    "ClusterRSVPPreference": "models",
    "RSVP": "models",
    "PriorityToken": "models",
    "EventExclusion": "models",
    # Enums are inner classes — resolved via their parent model.
    "Emphasis": "models",
    "ClusterStatus": "models",
    "RSVPStatus": "models",
    "TokenScope": "models",
}

__all__ = [
    "RSVP",
    "CalendarEvent",
    "ClusterRSVP",
    "ClusterRSVPPreference",
    "ClusterStatus",
    "Emphasis",
    "EventCluster",
    "EventExclusion",
    "EventTag",
    "PriorityToken",
    "RSVPStatus",
    "TokenScope",
    "cluster_drawn",
    "cluster_seat_assigned",
    "event_cancelled",
    "event_created",
    "event_starting_soon",
    "lottery_confirmation_expired",
    "lottery_drawn",
    "lottery_selected",
    "rsvp_status_changed",
    "waitlist_promoted",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submodule}", __name__)
    # Resolve inner-class enums via their parent model.
    if name == "Emphasis":
        return mod.CalendarEvent.Emphasis
    if name == "ClusterStatus":
        return mod.ClusterRSVP.Status
    if name == "RSVPStatus":
        return mod.RSVP.Status
    if name == "TokenScope":
        return mod.PriorityToken.Scope
    return getattr(mod, name)


def __dir__():
    return sorted([*globals(), *_LAZY])
