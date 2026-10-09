# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Partner API. Each change and its ledger row share the caller's transaction."""

from django.db import transaction
from django.db.models import F, Sum
from evennia.objects.models import ObjectDB

from .models import ResourceDefinition, ResourceGrant, ResourceHolding


class ResourceError(ValueError):
    pass


def _quantity(qty):
    if type(qty) is not int or qty <= 0:
        raise ResourceError("Quantity must be a positive whole number.")


def definition(key, *, active=True):
    query = ResourceDefinition.objects.filter(key=key)
    if active:
        query = query.filter(archived=False)
    resource = query.first()
    if resource is None:
        raise ResourceError(f"Unknown or archived resource: {key}.")
    return resource


def total_held(character):
    return (
        ResourceHolding.objects.filter(character=character).aggregate(total=Sum("quantity"))[
            "total"
        ]
        or 0
    )


def _change(character, key, qty, source, **metadata):
    if source not in dict(ResourceGrant._meta.get_field("source").choices):
        raise ResourceError("Unknown grant source.")
    by = metadata.pop("by", None)
    if by is not None:
        metadata["by_id"] = getattr(by, "pk", by)
    with transaction.atomic():
        # One lock order for all holdings and the batch: character, then holding.
        ObjectDB.objects.select_for_update().get(pk=character.pk)
        resource = definition(key, active=qty > 0)
        holding, _ = ResourceHolding.objects.get_or_create(character=character, resource=resource)
        query = ResourceHolding.objects.filter(pk=holding.pk)
        if qty < 0:
            query = query.filter(quantity__gte=-qty)
        if not query.update(quantity=F("quantity") + qty):
            raise ResourceError(f"Not enough {resource.name}.")
        return ResourceGrant.objects.create(
            character=character, resource=resource, quantity=qty, source=source, **metadata
        )


def grant(character, key, qty, source="staff", **metadata):
    _quantity(qty)
    return _change(character, key, qty, source, **metadata)


def spend(character, key, qty, reason, *, source="craft", **metadata):
    _quantity(qty)
    metadata["note"] = reason
    return _change(character, key, -qty, source, **metadata)
