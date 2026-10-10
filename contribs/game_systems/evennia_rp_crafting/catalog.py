# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicit catalogue seeding; keys omitted by a host are never removed."""

from django.core.validators import validate_slug
from django.db import transaction
from evennia_rp_resources.conf import categories

from . import conf
from .models import NicheDefinition


def category_cost(value):
    if not isinstance(value, dict) or any(
        key not in categories() or not conf.positive(amount) for key, amount in value.items()
    ):
        raise ValueError("Costs must map configured resource categories to positive whole units.")
    if sum(value.values()) > conf.MAX_AMOUNT:
        raise ValueError("Resource cost exceeds the supported range.")
    return dict(value)


def validate_niche(niche):
    from .behaviours import registry

    niche.full_clean(validate_unique=False, validate_constraints=False)
    validate_slug(niche.key)
    if not conf.nonnegative(niche.unlock_money):
        raise ValueError("Niche money costs must be nonnegative whole amounts.")
    known = registry()
    if (
        not isinstance(niche.behaviours, list)
        or not niche.behaviours
        or any(key not in known for key in niche.behaviours)
    ):
        raise ValueError("Niches must list registered behaviour keys.")
    if (
        not isinstance(niche.input_categories, list)
        or not niche.input_categories
        or any(key not in categories() for key in niche.input_categories)
    ):
        raise ValueError("Niches must list configured input categories.")
    if set(category_cost(niche.unlock_resources)) - set(niche.input_categories):
        raise ValueError("Unlock costs must use the niche's input categories.")


@transaction.atomic
def seed_catalog(*, update=False):
    provider = conf.hook("RP_CRAFTING_CATALOG")
    seen = set()
    result = []
    for entry in provider() if provider else []:
        values = dict(entry)
        key = values.pop("key")
        if key in seen:
            raise ValueError(f"Duplicate niche key: {key}")
        seen.add(key)
        validate_niche(NicheDefinition(key=key, **values))
        method = (
            NicheDefinition.objects.update_or_create
            if update
            else NicheDefinition.objects.get_or_create
        )
        result.append(method(key=key, defaults=values)[0])
    return result
