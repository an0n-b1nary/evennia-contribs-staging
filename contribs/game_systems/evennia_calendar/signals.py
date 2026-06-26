# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signals for evennia_calendar.

event_created          — new CalendarEvent saved.
                         kwargs: event (CalendarEvent)
event_cancelled        — event marked is_cancelled=True.
                         kwargs: event (CalendarEvent)
event_starting_soon    — 24h reminder (fired by scheduler sweep).
                         kwargs: event (CalendarEvent)
lottery_drawn          — standalone lottery draw completed.
                         kwargs: event (CalendarEvent), selected (list[RSVP]),
                                 lottery_entered_remaining (int)
lottery_selected       — a single player was selected in a standalone draw.
                         kwargs: event (CalendarEvent), rsvp (RSVP)
lottery_confirmation_expired — a LOTTERY_SELECTED or INVITED RSVP was released
                               at the 48h deadline.
                               kwargs: event (CalendarEvent), rsvp (RSVP)
rsvp_status_changed    — any RSVP status transition.
                         kwargs: rsvp (RSVP), old_status (str), new_status (str)
waitlist_promoted      — a WAITLISTED RSVP was moved to CONFIRMED or INVITED.
                         kwargs: event (CalendarEvent), rsvp (RSVP)
cluster_drawn          — cluster-wide lottery draw completed.
                         kwargs: cluster (EventCluster),
                                 seated_count (int), unseated_count (int)
cluster_seat_assigned  — a single player was assigned to a member event during
                         a cluster draw.
                         kwargs: cluster (EventCluster),
                                 cluster_rsvp (ClusterRSVP),
                                 rsvp (RSVP), rank_achieved (int)
"""

from django.dispatch import Signal

event_created = Signal()
event_cancelled = Signal()
event_starting_soon = Signal()

lottery_drawn = Signal()
lottery_selected = Signal()
lottery_confirmation_expired = Signal()

rsvp_status_changed = Signal()
waitlist_promoted = Signal()

cluster_drawn = Signal()
cluster_seat_assigned = Signal()
