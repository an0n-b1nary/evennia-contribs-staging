# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Material drafts and short-lived confirmations for Workshop investments."""

from uuid import uuid4

from django.apps import apps
from django.core import signing
from django.db.models import F
from evennia.objects.models import ObjectDB
from evennia.utils.dbserialize import deserialize
from evennia_rp_resources.models import ResourceDefinition

from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import conf, services
from .behaviours import registry
from .command_syntax import select_resource
from .errors import CraftingError
from .models import NicheDefinition

DRAFT_KEY = "rp_workshop_unlock_drafts"
SALT = "rp-crafting-unlock-v1"


def _drafts(actor):
    # Reserve SQLite's writer before reading, and serialize PostgreSQL callers.
    ObjectDB.objects.filter(pk=actor.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    actor.attributes.reset_cache()
    return deserialize(actor.attributes.get(DRAFT_KEY, default={}))


@atomic_objects
def select(actor, key, value, *, remove=False):
    drafts = _drafts(actor)
    services._require(actor, spending=False)
    services.niche(key)
    draft = drafts.get(key, {"selected": {}})
    select_resource(draft, value, remove=remove)
    # Any edit invalidates previous previews, even if later edited back.
    draft.pop("nonce", None)
    drafts[key] = draft
    actor.attributes.add(DRAFT_KEY, drafts)
    return draft["selected"]


@atomic_objects
def cancel(actor, key):
    drafts = _drafts(actor)
    drafts.pop(key, None)
    actor.attributes.add(DRAFT_KEY, drafts)


def _review(actor, key, draft):
    services._require(actor)
    workshop = services._workshop(actor)
    definition = NicheDefinition.objects.select_for_update().get(pk=services.niche(key).pk)
    implementations = registry()
    available = [
        name
        for name in definition.behaviours
        if name in implementations
        and implementations[name].available()
        and conf.component_visible(actor, name)
    ]
    if not available:
        raise CraftingError("This niche's behaviours are unavailable.")
    held = services.active_unlocks(workshop)
    if held.filter(niche=definition).exists():
        raise CraftingError("You already hold that niche.")
    cap = get("RP_CRAFTING_NICHE_CAP")
    if held.count() >= cap:
        raise CraftingError("Your Workshop is at its niche cap. Abandon a niche first.")
    cost = services.unlock_cost(definition, held.count())
    # Definition edits cannot race the preview validation and final spending.
    resource_rows = list(
        ResourceDefinition.objects.select_for_update()
        .filter(key__in=draft["selected"])
        .order_by("key")
        .values("key", "name", "category", "archived")
    )
    selected = services.payment(draft["selected"], cost["resources"], definition.input_categories)
    money_label = ""
    if apps.is_installed("evennia_economy"):
        from evennia_economy.conf import currency

        money_label = currency(cost["money"])
    guards = {
        "actor": actor.pk,
        "niche": key,
        "definition": {
            field: getattr(definition, field)
            for field in (
                "pk",
                "name",
                "description",
                "behaviours",
                "input_categories",
                "unlock_money",
                "unlock_resources",
                "archived",
            )
        },
        "cost": cost,
        "money_label": money_label,
        "selected": selected,
        "resources": resource_rows,
        "available": available,
        "cap": cap,
        # Include abandoned rows: unlocking/abandoning cannot restore old tokens.
        "history": [
            [row.pk, row.niche_id, row.abandoned_at.isoformat() if row.abandoned_at else None]
            for row in workshop.unlocks.order_by("pk")
        ],
        "nonce": draft.get("nonce"),
    }
    return definition, cost, selected, guards


@atomic_objects
def preview(actor, key):
    drafts = _drafts(actor)
    draft = drafts.get(key, {"selected": {}})
    draft["nonce"] = uuid4().hex
    definition, cost, selected, guards = _review(actor, key, draft)
    token = "confirm-" + signing.dumps(guards, salt=SALT, compress=True)
    drafts[key] = draft
    actor.attributes.add(DRAFT_KEY, drafts)
    return definition, cost, selected, token


@atomic_objects
def confirm(actor, key, token):
    try:
        if not token.startswith("confirm-"):
            raise signing.BadSignature()
        confirmed = signing.loads(token.removeprefix("confirm-"), salt=SALT, max_age=900)
    except signing.BadSignature:
        raise CraftingError("Invalid or expired token; request a new unlock preview.") from None
    drafts = _drafts(actor)
    draft = drafts.get(key)
    if not draft or "nonce" not in draft:
        raise CraftingError("Request a new unlock preview before confirming.")
    _, _, selected, expected = _review(actor, key, draft)
    if confirmed != expected:
        raise CraftingError("Workshop or payment details changed; request a new unlock preview.")
    result = services.unlock(actor, key, selected)
    del drafts[key]
    actor.attributes.add(DRAFT_KEY, drafts)
    return result
