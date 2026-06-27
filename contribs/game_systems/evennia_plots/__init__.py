# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_plots — narrative plot-thread and story-arc system for Evennia games.

Public API (model classes loaded lazily to avoid AppRegistryNotReady):

    PlotTag          — tag applied to plot threads and arcs
    PlotThread       — named narrative container (active / concluded / archived)
    PlotArc          — staff-only storyline grouping one or more plot threads
    PlotParticipant  — per-character membership row on a PlotThread
    PlotUpdate       — append-only journal block (thread or arc), version-tracked
    ThreadLink       — directional sequel / related-story connection between threads

    ScenePlotLink    — bridge: Scene (integer soft-ref) ↔ PlotThread
    PlotCalendarLink — bridge: PlotThread ↔ CalendarEvent (integer soft-ref)
    PlotBoardLink    — bridge: PlotThread ↔ board Post (integer soft-ref + is_ic_post)
    PlotBonusCredit  — XP-eligibility row: PlotThread ↔ character (integer soft-ref)

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    plot_thread_created, plot_thread_activated, plot_thread_concluded,
    plot_thread_archived, scene_linked_to_thread, post_linked_to_thread,
    event_linked_to_thread, thread_link_accepted, plot_update_created,
    plot_thread_edited, arc_type_changed, arc_currency_changed

Commands (import explicitly):

    from evennia_plots.commands import CmdPlot, CmdArc, CmdHook

Web/API surface (requires [web] extra):

    from evennia_plots.views import PlotListView, PlotDetailView, ...
    from evennia_plots.api.views import PlotThreadViewSet
"""

__version__ = "0.1.0"

from evennia_plots.signals import (
    arc_currency_changed,
    arc_type_changed,
    event_linked_to_thread,
    plot_thread_activated,
    plot_thread_archived,
    plot_thread_concluded,
    plot_thread_created,
    plot_thread_edited,
    plot_update_created,
    post_linked_to_thread,
    scene_linked_to_thread,
    thread_link_accepted,
)

_LAZY = {
    "PlotTag": "models",
    "PlotThread": "models",
    "PlotArc": "models",
    "PlotParticipant": "models",
    "PlotUpdate": "models",
    "ThreadLink": "models",
    "ScenePlotLink": "models",
    "PlotCalendarLink": "models",
    "PlotBoardLink": "models",
    "PlotBonusCredit": "models",
}

__all__ = [  # noqa: RUF022
    # Domain models
    "PlotTag",
    "PlotThread",
    "PlotArc",
    "PlotParticipant",
    "PlotUpdate",
    "ThreadLink",
    # Bridges
    "ScenePlotLink",
    "PlotCalendarLink",
    "PlotBoardLink",
    "PlotBonusCredit",
    # Signals
    "arc_currency_changed",
    "arc_type_changed",
    "event_linked_to_thread",
    "plot_thread_activated",
    "plot_thread_archived",
    "plot_thread_concluded",
    "plot_thread_created",
    "plot_thread_edited",
    "plot_update_created",
    "post_linked_to_thread",
    "scene_linked_to_thread",
    "thread_link_accepted",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
