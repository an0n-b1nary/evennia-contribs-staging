# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
import math

from django.apps import apps
from django.db.models import Sum

from evennia_links.runtime import get

from . import conf
from .models import CraftRecord, NicheDefinition, NicheUnlock, Workshop


def caps(sender, character, **kwargs):
    count = NicheUnlock.objects.filter(
        workshop__character=character, abandoned_at__isnull=True
    ).count()
    if not count:
        return {"workshops": {"money": 0, "resources": 0}}
    definitions = NicheDefinition.objects.filter(archived=False)
    factor = conf.multiplier(count + 1)
    next_resources = max(
        (sum(row.unlock_resources.values()) * factor for row in definitions), default=0
    )
    resource_raise = max(
        count * get("RP_CRAFTING_RESOURCE_CAP_RAISE"), next_resources - get("RP_RESOURCES_BASE_CAP")
    )
    money_raise = 0
    if apps.is_installed("evennia_economy"):
        next_money = max((row.unlock_money * factor for row in definitions), default=0)
        base = math.ceil(get("RP_ECONOMY_WEEKLY_AMOUNT") * get("RP_ECONOMY_BASE_CAP_WEEKS"))
        money_raise = max(count * get("RP_CRAFTING_MONEY_CAP_RAISE"), next_money - base)
    return {"workshops": {"money": money_raise, "resources": resource_raise}}


def figures(sender, **kwargs):
    return {
        "crafting": {
            "workshops": Workshop.objects.count(),
            "active_niches": NicheUnlock.objects.filter(abandoned_at__isnull=True).count(),
            "invested_money": Workshop.objects.aggregate(total=Sum("invested_money"))["total"] or 0,
            "crafts": CraftRecord.objects.count(),
        }
    }
