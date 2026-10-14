# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Capture craft-input value in UBI-weeks; later prices never affect credit."""

from decimal import Decimal, InvalidOperation

from django.conf import settings
from evennia_rp_resources.models import ResourceDefinition

from .errors import CraftingError


def furnishing_value(selected, money):
    weights = getattr(
        settings,
        "RP_CRAFTING_FURNISHING_CATEGORY_VALUES",
        {
            "materials": 1,
            "essences": 2,
            "provisions": 1,
        },
    )
    try:
        reference = Decimal(str(getattr(settings, "RP_CRAFTING_FURNISHING_REFERENCE", 1)))
        money_value = Decimal(str(getattr(settings, "RP_CRAFTING_FURNISHING_COIN_VALUE", "0.01")))
        basic = Decimal(str(getattr(settings, "RP_CRAFTING_BASIC_FIXTURE_WEEKS", "0.2")))
        values = {key: Decimal(str(value)) for key, value in weights.items()}
        if (
            not reference.is_finite()
            or reference <= 0
            or any(
                not value.is_finite() or value < 0
                for value in [basic, money_value, *values.values()]
            )
        ):
            raise ValueError
        total = Decimal(money) * money_value
        for resource in ResourceDefinition.objects.filter(key__in=selected):
            total += selected[resource.key] * values[resource.category]
        result = (basic * total / reference).quantize(Decimal("0.000001"))
        if not result.is_finite() or result > Decimal("99999999999999"):
            raise ValueError
        return result
    except (InvalidOperation, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CraftingError("The furnishing valuation settings are invalid.") from exc
