# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Idempotent, explicit catalogue seeding; omitted keys are never deleted."""

from django.core.validators import validate_slug
from django.db import transaction

from . import conf
from .models import ResourceDefinition


@transaction.atomic
def seed_catalog(*, update=False):
    provider = conf.hook("RP_RESOURCES_CATALOG")
    entries = provider() if provider else []
    seen = set()
    result = []
    for entry in entries:
        values = dict(entry)
        key = values.pop("key")
        validate_slug(key)
        if key in seen:
            raise ValueError(f"Duplicate resource key: {key}")
        seen.add(key)
        if values["category"] not in conf.categories():
            raise ValueError(f"Unknown resource category for {key}")
        probe = ResourceDefinition(key=key, **values)
        probe.full_clean(validate_unique=False, validate_constraints=False)
        if (
            probe.weight <= 0
            or not isinstance(probe.terrains, list)
            or any(not isinstance(value, str) for value in probe.terrains)
        ):
            raise ValueError(f"Invalid weight or terrains for {key}")
        method = (
            ResourceDefinition.objects.update_or_create
            if update
            else ResourceDefinition.objects.get_or_create
        )
        resource, _ = method(key=key, defaults=values)
        result.append(resource)
    return result
