# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional resource asset provider; imported only with economy installed."""

import re

from django.db.models import Sum
from evennia_economy.services import EconomyError

from .models import ResourceDefinition, ResourceGrant, ResourceHolding
from .services import ResourceError, definition, grant, spend


class ResourceAssetProvider:
    def describe(self, key):
        try:
            return definition(key, active=False).name
        except ResourceError as exc:
            raise EconomyError(str(exc)) from exc

    def parse(self, text):
        match = re.fullmatch(r"([0-9]+)\s+(.+)", text)
        if not match:
            return None
        name = match[2].strip()
        matches = ResourceDefinition.objects.filter(
            key__iexact=name
        ) | ResourceDefinition.objects.filter(name__iexact=name)
        keys = list(matches.distinct().values_list("key", flat=True))
        return (keys[0], int(match[1])) if len(keys) == 1 else None

    def check(self, giver, recipient, key, quantity):
        try:
            definition(key)
        except ResourceError as exc:
            raise EconomyError(str(exc)) from exc
        held = (
            ResourceHolding.objects.filter(character=giver, resource__key=key)
            .values_list("quantity", flat=True)
            .first()
            or 0
        )
        if held < quantity:
            raise EconomyError(f"Not enough {key}.")

    def debit(self, character, key, quantity, exchange_id):
        try:
            spend(character, key, quantity, "Exchange", source="exchange", exchange_id=exchange_id)
        except ResourceError as exc:
            raise EconomyError(str(exc)) from exc

    def credit(self, character, key, quantity, exchange_id):
        try:
            grant(character, key, quantity, "exchange", exchange_id=exchange_id)
        except ResourceError as exc:
            raise EconomyError(str(exc)) from exc


def provide_assets(sender, **kwargs):
    return {"resource": ResourceAssetProvider()}


def provide_figures(sender, **kwargs):
    held = ResourceHolding.objects.aggregate(total=Sum("quantity"))["total"] or 0
    return {"resources": {"held": held, "ledger_rows": ResourceGrant.objects.count()}}
