# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Canonical specs: [{kind, key, quantity}]. Providers own their counters.

Collector receivers return {kind: provider}. A provider implements describe(key),
check(giver, recipient, key, quantity), debit(character, key, quantity, exchange_id)
and credit(character, key, quantity, exchange_id). All methods run inside the
exchange transaction; check must raise on refusal and writes must be transactional.
An optional available(character) -> bool hides the kind from that character (for
example while its package is unrevealed): it won't parse, and offers involving
them refuse it. Money and items are reserved native kinds. Unknown providers
fail closed.
"""

import logging
import re
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from evennia.objects.models import ObjectDB

from evennia_links.collect import collect_dicts

from .services import EconomyError, _adjust, balance, quantity
from .signals import asset_providers

logger = logging.getLogger("evennia")


def providers(*characters):
    """Provider kinds, limited to those available to every given character."""
    return {
        key: value
        for key, value in collect_dicts(asset_providers, sender=OfferAssets).items()
        if key not in ("money", "item")
        and all(
            not hasattr(value, "available") or value.available(character)
            for character in characters
        )
    }


class OfferAssets:
    """Collector sender, with no import dependency on optional asset packages."""


def normalize(spec):
    if not isinstance(spec, list) or len(spec) > 100:
        raise EconomyError("Supply a list of at most 100 assets.")
    totals = defaultdict(int)
    for entry in spec:
        if not isinstance(entry, dict) or set(entry) != {"kind", "key", "quantity"}:
            raise EconomyError("Each asset needs kind, key and quantity.")
        kind, key, count = entry["kind"], entry["key"], quantity(entry["quantity"])
        if not isinstance(kind, str) or not isinstance(key, str) or len(key) > 255:
            raise EconomyError("Invalid asset identifier.")
        if kind == "money" and key != "":
            raise EconomyError("Money has no asset key.")
        if kind == "item" and (count != 1 or not key.isdecimal()):
            raise EconomyError("An item is one object, identified by its dbref.")
        totals[kind, key] += count
        quantity(totals[kind, key])
        if kind == "item" and totals[kind, key] != 1:
            raise EconomyError("An item may only appear once.")
    return [
        {"kind": kind, "key": key, "quantity": count}
        for (kind, key), count in sorted(totals.items())
    ]


def parse_spec(character, text, *, items_only=False):
    """Explicit prefixes avoid guessing: money:40, resource:grain:3, item:#12.

    Ordinary `40 coins` and inventory names are also accepted. A host provider
    may implement parse(text) -> (key, quantity) for its natural-language form.
    With `items_only` (the economy is hidden from `character`), every piece is
    a carried item, so nothing hints at money or other asset kinds.
    """
    result = []
    available = {} if items_only else providers(character)
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            raise EconomyError("Empty asset. Separate assets with commas.")
        if items_only:
            result.append(_carried_item(character, piece))
            continue
        if piece.startswith("money:"):
            try:
                result.append({"kind": "money", "key": "", "quantity": int(piece[6:])})
            except ValueError:
                raise EconomyError("Use money:<whole amount>.") from None
            continue
        if ":" in piece and not piece.startswith("item:"):
            parts = piece.split(":")
            if len(parts) != 3 or parts[0] not in available:
                raise EconomyError("Unknown asset provider or invalid kind:key:quantity.")
            try:
                result.append({"kind": parts[0], "key": parts[1], "quantity": int(parts[2])})
            except ValueError:
                raise EconomyError("Asset quantity must be a whole number.") from None
            continue
        nouns = getattr(settings, "RP_ECONOMY_CURRENCY", ("coin", "coins"))
        match = re.fullmatch(r"([0-9]+)\s+(.+)", piece)
        if match and match[2].casefold() in {str(n).casefold() for n in nouns}:
            result.append({"kind": "money", "key": "", "quantity": int(match[1])})
            continue
        if not piece.startswith("item:"):
            matches = [
                (kind, provider.parse(piece))
                for kind, provider in available.items()
                if hasattr(provider, "parse")
            ]
            matches = [(kind, parsed) for kind, parsed in matches if parsed is not None]
            if len(matches) > 1:
                raise EconomyError("Ambiguous asset; use kind:key:quantity.")
            if matches:
                kind, (key, count) = matches[0]
                result.append({"kind": kind, "key": key, "quantity": count})
                continue
        result.append(_carried_item(character, piece))
    return normalize(result)


def _carried_item(character, piece):
    name = piece[5:] if piece.startswith("item:") else piece
    objects = character.search(name, candidates=character.contents, quiet=True)
    if len(objects) != 1:
        raise EconomyError(f"No unique carried item matches {name!r}.")
    return {"kind": "item", "key": str(objects[0].pk), "quantity": 1}


def describe(spec):
    available = providers()
    labels = []
    from .conf import currency

    for asset in spec:
        kind, key, count = asset["kind"], asset["key"], asset["quantity"]
        if kind == "money":
            labels.append(currency(count))
        elif kind == "item":
            name = ObjectDB.objects.filter(pk=int(key)).values_list("db_key", flat=True).first()
            labels.append(name or f"deleted item #{key}")
        elif kind in available:
            labels.append(f"{count} {available[kind].describe(key)}")
        else:
            labels.append(f"{count} {kind}:{key} (unavailable)")
    return ", ".join(labels) or "nothing"


def check(giver, recipient, spec):
    available = providers(giver, recipient)
    for asset in spec:
        kind, key, count = asset["kind"], asset["key"], asset["quantity"]
        if kind == "money":
            if balance(giver) < count:
                raise EconomyError("Insufficient funds.")
        elif kind == "item":
            item = ObjectDB.objects.select_for_update().filter(pk=int(key)).first()
            location = (
                ObjectDB.objects.filter(pk=int(key))
                .values_list("db_location_id", flat=True)
                .first()
            )
            if not item or location != giver.pk:
                raise EconomyError("That item is no longer carried by its giver.")
            if item.destination or item.has_account or item.pk in (giver.pk, recipient.pk):
                raise EconomyError("That object cannot be traded.")
            if not item.at_pre_give(giver, recipient):
                raise EconomyError("That item cannot be given. Remove worn gear first.")
            if not item.at_pre_move(
                recipient, move_type="give"
            ) or not recipient.at_pre_object_receive(item, giver, move_type="give"):
                raise EconomyError("The item or recipient refused the move.")
        else:
            provider = available.get(kind)
            if provider is None:
                raise EconomyError(f"The {kind} asset provider is unavailable.")
            provider.check(giver, recipient, key, count)


def _finish_item(item, giver, recipient):
    """Publish cache and hook changes only after the exchange commits.

    Each step runs on its own, so one failing hook can't skip the others (an
    item's at_post_move is where equipment seals a handed-over item).
    """

    def relocate():
        # refresh_from_db() reuses Evennia's identity-mapped ObjectDB instance,
        # which can still carry the old FK. Read the scalar directly instead.
        location_id = (
            ObjectDB.objects.filter(pk=item.pk).values_list("db_location_id", flat=True).get()
        )
        item.db_location = ObjectDB.objects.get(pk=location_id) if location_id else None
        giver.contents_cache.remove(item)
        recipient.contents_cache.add(item)

    for step in (
        relocate,
        lambda: giver.at_object_leave(item, recipient, move_type="give"),
        lambda: recipient.at_object_receive(item, giver, move_type="give"),
        lambda: item.at_post_move(giver, move_type="give"),
        lambda: item.at_give(giver, recipient),
    ):
        try:
            step()
        except Exception:
            logger.exception("Economy item post-transfer hook failed for #%s", item.pk)


def move(giver, recipient, spec, exchange_id):
    available = providers(giver, recipient)
    for asset in spec:
        kind, key, count = asset["kind"], asset["key"], asset["quantity"]
        if kind == "money":
            _adjust(giver, -count)
            _adjust(recipient, count)
        elif kind == "item":
            item = ObjectDB.objects.get(pk=int(key))
            if not ObjectDB.objects.filter(pk=item.pk, db_location_id=giver.pk).update(
                db_location_id=recipient.pk
            ):
                raise EconomyError("Item ownership changed during the exchange.")
            transaction.on_commit(lambda obj=item: _finish_item(obj, giver, recipient))
        else:
            provider = available.get(kind)
            if provider is None:
                raise EconomyError(f"The {kind} asset provider is unavailable.")
            provider.debit(giver, key, count, exchange_id)
            provider.credit(recipient, key, count, exchange_id)
