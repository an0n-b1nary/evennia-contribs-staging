# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Shared collector-signal helper, and a dotted-path import helper.

Where ``connect_on_ready()`` is for *notification* signals (fire and
forget), ``collect_dicts()`` is for *collector* signals: the sender asks
every connected app a question and merges their answers.

Usage::

    # Signal owner (evennia_maps/signals.py):
    collect_tile_overlays = Signal()   # kwargs: room_ids, staff

    # Consumer (the code that needs the merged answer):
    from evennia_links.collect import collect_dicts
    overlays = collect_dicts(
        collect_tile_overlays, sender=MapPlane, room_ids=room_ids, staff=staff
    )

    # Provider (evennia_scenes/integrations/maps.py), connected in apps.py ready():
    def provide(sender, room_ids, staff, **kwargs):
        return {"has_active_scene": {...}}

The point of the pattern is that the *asking* app never imports the
*answering* apps. ``evennia_maps`` can render an overlay owned by
``evennia_lore`` without importing it, which is what lets both sides be
extracted, installed, and uninstalled independently.

**Contract for providers:**

- Return a dict, or None/{} to contribute nothing.
- Write disjoint top-level keys. Receiver order is not guaranteed and must
  not matter — later responses overwrite earlier ones on a key collision,
  so two providers claiming the same key is a bug in the providers, not
  something this helper arbitrates.
- A provider that raises, or returns a non-dict, is logged and skipped. It
  degrades its own overlay to absent; it never breaks the caller.

This is the shared form of a pattern that shipped first as
``world.utils.collect`` in the source game — keep the two in step.
"""

import logging
from importlib import import_module

logger = logging.getLogger("evennia")


def collect_dicts(signal, **kwargs):
    """
    Send *signal* to every receiver and merge their dict responses into one.

    Uses send_robust(), so a raising receiver comes back as the response
    value instead of propagating — one broken provider must never 500 the
    request that asked the question. Non-dict responses are dropped for the
    same reason: send_robust() only guards against receivers that *raise*,
    and an update() against a list would otherwise take the caller down
    just as hard as an unhandled exception would.

    Args:
        signal: A Django Signal instance.
        **kwargs: Passed straight through to send_robust(), including the
            required `sender`.

    Returns:
        dict: The merged responses. Empty if nothing was connected.
    """
    merged = {}
    for receiver, response in signal.send_robust(**kwargs):
        if isinstance(response, Exception):
            logger.error(
                "collect_dicts: receiver %r raised; skipping its contribution",
                receiver,
                exc_info=response,
            )
            continue
        if response is None:
            continue
        if not isinstance(response, dict):
            logger.error(
                "collect_dicts: receiver %r returned %s, expected dict; skipping",
                receiver,
                type(response).__name__,
            )
            continue
        merged.update(response)
    return merged


def resolve_dotted(path):
    """
    Import and return the object at a dotted ``"pkg.mod.attr"`` path.

    Args:
        path: A dotted path string, or None/empty.

    Returns:
        The imported attribute, or None if *path* is None/empty.

    Raises:
        ImportError: if the module cannot be imported.
        AttributeError: if the module has no such attribute.
    """
    if not path:
        return None
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)
