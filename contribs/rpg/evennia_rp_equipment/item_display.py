# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional keyed transforms for item descriptions and worn lines.

Providers register once during AppConfig.ready(). Equipment owns the rendering
path; partners own their prose. Base transforms run before extras, in key order within each phase, and receive
(item, looker, context, text), returning the complete transformed text.
"""

import logging

logger = logging.getLogger("evennia")
_providers = {}


def register(key, provider, *, phase="extra"):
    """Register/replace a stable provider key; repeated ready() calls are safe."""
    if phase not in ("base", "extra"):
        raise ValueError("Display phases are base or extra.")
    if not isinstance(key, str) or not key or not callable(provider):
        raise ValueError("Display providers need a nonempty key and callable.")
    _providers[key] = (phase, provider)


def render(item, looker, context, text):
    """Render once, preserving the prior text when an optional provider fails."""
    if context not in ("desc", "worn"):
        raise ValueError("Unknown equipment display context.")
    providers = sorted(_providers.items(), key=lambda row: (row[1][0] != "base", row[0]))
    for key, (_, provider) in providers:
        try:
            result = provider(item, looker, context, text)
            if not isinstance(result, str):
                raise TypeError("Display providers must return text.")
            text = result
        except Exception:
            logger.exception("Equipment display provider %s failed", key)
    return text
