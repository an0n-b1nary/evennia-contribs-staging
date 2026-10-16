# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Paid, validated partner metadata stored inside the immutable craft snapshot."""

import logging
from collections import Counter

from evennia_links.collect import collect_dicts

from . import conf, signals
from .errors import CraftingError

logger = logging.getLogger("evennia")


def registry():
    return collect_dicts(signals.collect_facets, sender=None)


def prepare(actor, requested, composition):
    if requested is None:
        return {}, dict(composition.resources)
    if not isinstance(requested, dict):
        raise CraftingError("Craft facets must be a mapping.")
    providers = registry()
    if set(requested) - set(providers):
        raise CraftingError("That crafting facet is unavailable.")
    normalized, total = {}, Counter(composition.resources)
    for key, config in sorted(requested.items()):
        try:
            data, costs = providers[key].prepare(actor, config, composition)
        except ValueError as exc:
            raise CraftingError(str(exc)) from None
        if data:
            normalized[key] = data
            total.update(costs)
    if not total or sum(total.values()) > conf.MAX_AMOUNT:
        raise CraftingError("Craft costs exceed the supported range.")
    return normalized, dict(total)


def display(item, looker):
    if looker is None or not item.access(looker, "view", default=True):
        return ""
    record = item.craft_record
    if record is None:
        return ""
    providers = registry()
    lines = []
    for key, data in record.prose.get("facets", {}).items():
        provider = providers.get(key)
        if provider is not None:
            try:
                lines.extend(provider.display(looker, data))
            except Exception:
                # A missing/broken optional provider must hide its gated text.
                logger.exception("Craft facet %s could not render", key)
    return "\n".join(lines)


def read_lines(actor, item, record, number, canonical):
    lines = []
    for receiver, response in signals.page_read.send_robust(
        sender=None,
        actor=actor,
        item=item,
        record=record,
        number=number,
        canonical=canonical,
    ):
        if isinstance(response, Exception):
            logger.error("Craft page reader %r failed", receiver, exc_info=response)
        elif isinstance(response, str) and response:
            lines.append(response)
    return "\n".join(lines)
