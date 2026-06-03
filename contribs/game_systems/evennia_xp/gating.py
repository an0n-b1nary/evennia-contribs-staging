# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP multiplier gating seam for evennia_xp.

Provides a single callable — resolve_xp_multiplier() — that delegates to the
game-supplied XP_MULTIPLIER_RESOLVER setting.  When no resolver is configured,
all multipliers are 1.0 (full XP rate).

Setting::

    XP_MULTIPLIER_RESOLVER = "myapp.xp_gating.resolve_xp_multiplier"

The resolver callable must have the signature::

    def resolve_xp_multiplier(source, *, thread=None, room=None, character=None):
        # Return a Decimal (e.g. Decimal("1.0"), Decimal("0.5"), Decimal("0.0"))
        ...

The *source* argument is one of the XPLog.SourceType value strings
("rp_session", "cutscene", "lore", "thread_bonus", etc.).

The *thread*, *room*, and *character* kwargs are context objects for games
that support per-thread arcs, regional multipliers, or character overrides.
They may be None when the context is unavailable.

thread_pauses_xp(source, **ctx) is a convenience predicate: True when the
multiplier resolves to 0.0. Equivalent to calling resolve_xp_multiplier and
checking == 0.
"""

import logging
from decimal import Decimal
from importlib import import_module

from django.conf import settings

logger = logging.getLogger("evennia")


def _resolve_dotted(path):
    """Import and return the callable at *path*."""
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


def resolve_xp_multiplier(source: str, *, thread=None, room=None, character=None) -> Decimal:
    """Return the XP multiplier for *source* given the current game context.

    Delegates to XP_MULTIPLIER_RESOLVER if configured; returns Decimal("1.0")
    when unset or when the resolver raises.

    Args:
        source: XPLog.SourceType value string, e.g. "rp_session".
        thread: PlotThread-like object (optional — for per-thread arc context).
        room: Room-like object (optional — for regional arc context).
        character: Character-like object (optional — for character overrides).

    Returns:
        Decimal multiplier. 1.0 = full rate, 0.0 = paused, 2.0 = doubled.
    """
    resolver_path = getattr(settings, "XP_MULTIPLIER_RESOLVER", None)
    if not resolver_path:
        return Decimal("1.0")
    try:
        fn = _resolve_dotted(resolver_path)
        return Decimal(str(fn(source, thread=thread, room=room, character=character)))
    except Exception:
        logger.exception(
            "XP multiplier resolver %r raised an exception — defaulting to 1.0",
            resolver_path,
        )
        return Decimal("1.0")


def thread_pauses_xp(source: str = "thread_bonus", **ctx) -> bool:
    """Return True if XP for *source* is currently paused (multiplier == 0).

    Convenience predicate for callers that only need a boolean gate.

    Args:
        source: XPLog.SourceType value string. Defaults to "thread_bonus".
        **ctx: Passed as keyword args to resolve_xp_multiplier
              (thread=, room=, character=).
    """
    return resolve_xp_multiplier(source, **ctx) == Decimal("0.0")
