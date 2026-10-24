# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable Tactics; neither creating a profile nor selecting one opts PCs in."""

from django.db import transaction
from django.utils.text import slugify

from evennia_links import runtime

from .data import REACTIONS, CombatError


def profile(character):
    from .models import Tactics

    row = Tactics.objects.filter(character=character, active=True).first()
    return (
        {
            key: getattr(row, key)
            for key in (
                "appetite",
                "preferred_reaction",
                "preferred_moves",
                "rps_appetite",
                "target_policy",
                "action_weights",
            )
        }
        if row
        else {}
    )


def validate(values):
    if not isinstance(values, dict):
        raise CombatError("Use a Tactics mapping with documented fields.")
    allowed = {
        "appetite",
        "preferred_reaction",
        "preferred_moves",
        "rps_appetite",
        "target_policy",
        "action_weights",
    }
    if set(values) - allowed:
        raise CombatError("Unknown Tactics field.")
    for field in ("appetite", "rps_appetite"):
        if field in values and values[field] not in ("cautious", "balanced", "bold"):
            raise CombatError("Choose Cautious, Balanced or Bold.")
    if values.get("preferred_reaction", "") not in ("", *REACTIONS):
        raise CombatError("Unknown preferred reaction.")
    if values.get("target_policy", "random") not in (
        "random",
        "lowest_vitality",
        "provoker",
        "front_first",
    ):
        raise CombatError("Unknown target policy.")
    if "action_weights" in values:
        weights = values["action_weights"]
        if (
            not isinstance(weights, dict)
            or set(weights) - {"standard", "special", "assist", "dispirit"}
            or not weights
            or any(type(v) is not int or not 0 <= v <= 100 for v in weights.values())
            or not any(weights.values())
        ):
            raise CombatError("Action weights must be whole numbers 0..100 with a positive total.")
    if "preferred_moves" in values and (
        not isinstance(values["preferred_moves"], list)
        or len(values["preferred_moves"]) > 10
        or any(
            type(v) is not str or not v or len(v) > 64 or slugify(v) != v
            for v in values["preferred_moves"]
        )
        or len(set(values["preferred_moves"])) != len(values["preferred_moves"])
    ):
        raise CombatError("Preferred moves must be a list of at most ten move keys.")


@transaction.atomic
def save(character, name, *, select=True, **values):
    from evennia.objects.models import ObjectDB

    from .models import Tactics

    if not runtime.get("RP_COMBAT_TACTICS_REVEALED"):
        raise CombatError("Tactics are not available yet.")
    ObjectDB.objects.select_for_update().get(pk=character.pk)
    validate(values)
    key = slugify(name)
    if not key or len(key) > 64 or not 1 <= len(name) <= 80:
        raise CombatError("Choose a short Tactics name.")
    from . import conf

    if not Tactics.objects.filter(character=character, key=key).exists() and Tactics.objects.filter(
        character=character
    ).count() >= conf.get("RP_COMBAT_TACTICS_LIMIT"):
        raise CombatError("Your Tactics library is full; delete or edit an existing preset.")
    if select:
        Tactics.objects.filter(character=character, active=True).update(active=False)
    defaults = {"name": name, **values}
    if select:
        defaults["active"] = True
    row, _ = Tactics.objects.update_or_create(character=character, key=key, defaults=defaults)
    return row


@transaction.atomic
def use(character, name):
    """Select one owned preset without rewriting it or enabling Auto-Resolve."""
    from evennia.objects.models import ObjectDB

    from .models import Tactics

    if not runtime.get("RP_COMBAT_TACTICS_REVEALED"):
        raise CombatError("Tactics are not available yet.")
    ObjectDB.objects.select_for_update().get(pk=character.pk)
    row = Tactics.objects.filter(character=character, key=slugify(name)).first()
    if row is None:
        raise CombatError("No such preset in your Tactics library.")
    Tactics.objects.filter(character=character, active=True).update(active=False)
    row.active = True
    row.save(update_fields=["active"])
    return row


@transaction.atomic
def delete(character, name):
    """Delete one owned preset; removing the active preset restores defaults."""
    from evennia.objects.models import ObjectDB

    from .models import Tactics

    if not runtime.get("RP_COMBAT_TACTICS_REVEALED"):
        raise CombatError("Tactics are not available yet.")
    ObjectDB.objects.select_for_update().get(pk=character.pk)
    row = Tactics.objects.filter(character=character, key=slugify(name)).first()
    if row is None:
        raise CombatError("No such preset in your Tactics library.")
    row.delete()


def set_field(character, name, field, text):
    """Parse one field; map entries use like key/weight items separated by commas."""
    text = text.strip()
    if field == "preferred_moves":
        value = [part.strip() for part in text.split(",") if part.strip()]
    elif field == "action_weights":
        value = {}
        for part in text.split(","):
            key, sep, weight = part.strip().partition("/")
            if not sep or key in value:
                raise CombatError("Use distinct action/weight entries separated by commas.")
            value[key] = int(weight)
    else:
        value = text
    return save(character, name, select=False, **{field: value})
