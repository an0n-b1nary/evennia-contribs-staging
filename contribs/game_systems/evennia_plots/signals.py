# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for evennia_plots.

Thread lifecycle signals:

    plot_thread_created   — new PlotThread created (proposed status).
    plot_thread_activated — PlotThread transitioned proposed → active.
    plot_thread_concluded — PlotThread concluded; bonus_xp computed.
                            kwargs: thread, bonus_xp
    plot_thread_archived  — PlotThread archived (stale, no bonus).

Content-linking signals:

    scene_linked_to_thread — a Scene was linked to a PlotThread.
                             kwargs: thread, scene, linked_by
    post_linked_to_thread  — a board Post was linked to a PlotThread.
                             kwargs: thread, post, linked_by
    event_linked_to_thread — a CalendarEvent was linked to a PlotThread.
                             kwargs: thread, event, linked_by

Thread-connection signals:

    thread_link_accepted — a pending ThreadLink was accepted by the target thread.
                           kwargs: link

Update and edit signals:

    plot_update_created — a PlotUpdate block was appended to a thread or arc.
                          kwargs: update
    plot_thread_edited  — a PlotThread's name/description/privacy was changed.
                          kwargs: thread, editor

Arc-typology signals (seam for XP-batch integration):

    arc_type_changed     — a PlotArc's arc_type was changed.
                           kwargs: arc, old_type, new_type
    arc_currency_changed — a PlotArc's is_current flag changed.
                           kwargs: arc, became_current (bool)

Connect these signals in your game's AppConfig.ready() or via evennia_links.connect_on_ready.
"""

from django.dispatch import Signal

# Thread lifecycle
plot_thread_created = Signal()
plot_thread_activated = Signal()
plot_thread_concluded = Signal()
plot_thread_archived = Signal()

# Content linking
scene_linked_to_thread = Signal()
post_linked_to_thread = Signal()
event_linked_to_thread = Signal()

# Thread connections
thread_link_accepted = Signal()

# Updates & edits
plot_update_created = Signal()
plot_thread_edited = Signal()

# Arc typology (XP-batch seam)
arc_type_changed = Signal()
arc_currency_changed = Signal()
