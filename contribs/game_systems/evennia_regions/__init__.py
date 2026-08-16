# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_regions — geographic grouping of rooms into named regions, for Evennia games.

Public API (model classes loaded lazily to avoid AppRegistryNotReady):

    Region              — a named geographic area
    RegionMembership    — bridge: Room (ObjectDB) <-> Region, many-to-many with
                           an is_primary flag for the single deterministic answer

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    region_created

Commands (import explicitly):

    from evennia_regions.commands import CmdRegion

Web/API surface (requires [web] extra):

    from evennia_regions.views import RegionListView, RegionDetailView
    from evennia_regions.api.views import RegionViewSet
"""

__version__ = "0.2.1"

from evennia_regions.signals import region_created

_LAZY = {
    "Region": "models",
    "RegionMembership": "models",
}

__all__ = [
    "Region",
    "RegionMembership",
    "region_created",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
