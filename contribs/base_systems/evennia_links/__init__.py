# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_links — shared abstract infrastructure for Evennia contrib bridge models.

Public API:

    AbstractLink            — minimal link base (created_at + create_link)
    AbstractAuthoredLink    — link with creator audit block
    AbstractVersion         — append-only version history for any text field
    AbstractArchived        — soft-archive mixin with default manager
    ArchivedManager         — manager that filters out archived records
    ArchivedQuerySet        — queryset with include_archived() helper
    connect_on_ready        — import-order-safe signal-registration helper

See each module's docstring for usage examples.

Note on imports: the model classes are loaded lazily (PEP 562 ``__getattr__``)
rather than imported at the top of this file. When ``evennia_links`` is listed
in ``INSTALLED_APPS``, Django imports this package during its app-loading phase,
*before* the app registry is ready. Eagerly importing the model modules here
would create model classes too early and raise ``AppRegistryNotReady``. Lazy
loading defers each model import until the name is first accessed (e.g. when a
consuming app's ``models.py`` does ``from evennia_links import AbstractLink``),
by which point the registry is ready.
"""

from .listeners import connect_on_ready

__version__ = "0.1.0"

# name -> submodule that defines it. Imported on first access via __getattr__.
_LAZY = {
    "AbstractLink": "links",
    "AbstractAuthoredLink": "links",
    "AbstractVersion": "versioning",
    "AbstractArchived": "archiving",
    "ArchivedManager": "archiving",
    "ArchivedQuerySet": "archiving",
}

__all__ = [
    "AbstractArchived",
    "AbstractAuthoredLink",
    "AbstractLink",
    "AbstractVersion",
    "ArchivedManager",
    "ArchivedQuerySet",
    "connect_on_ready",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
