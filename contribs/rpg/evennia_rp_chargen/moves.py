# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Free Signature libraries and equipped loadouts; combat remains optional."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from evennia_links import resolve_dotted, runtime
from evennia_rp_chargen import conf, guards, locks
from evennia_rp_chargen.services import ChargenError
from evennia_rp_rules.ruleset import get_ruleset

ACTIONS = ("attack", "spell", "assist", "dispirit")
EFFECT_ACTIONS = {
    "heal": ("assist",),
    "long_range": ("attack", "spell"),
    "evade_stance": ("attack", "spell"),
    "resist_stance": ("attack", "spell"),
    "overpower_stance": ("attack", "spell"),
    "strain": ("attack", "spell"),
}


def validate_definition(data, *, signature=True):
    """Validate durable authored tiers, not empowered/effect-adjusted tiers.

    The owning library validates structure even with combat uninstalled. A
    host validator may impose its element/domain vocabulary and extensions.
    """
    action = data.get("action", "attack")
    if action not in ACTIONS:
        raise ChargenError("Choose Attack, Spell, Assist or Dispirit.")
    effects = data.get("effects", [])
    if not isinstance(effects, list) or any(type(e) is not str for e in effects):
        raise ChargenError("Effects must be a list of effect names.")
    if len(set(effects)) != len(effects) or len(effects) > (2 if signature else 1):
        raise ChargenError(
            "Use distinct Effects: at most two on a Signature, one on an Improvised move."
        )
    for effect in effects:
        if effect not in EFFECT_ACTIONS or action not in EFFECT_ACTIONS[effect]:
            raise ChargenError(f"{effect} cannot be used with {action}.")
    power, accuracy = data.get("power", 0), data.get("accuracy", 0)
    if type(power) is not int or type(accuracy) is not int:
        raise ChargenError("Power and Accuracy must be whole tiers.")
    if action in ("attack", "spell"):
        budget = 2 if signature else 1
        if (
            power + accuracy != budget
            or min(power, accuracy) < -2
            or max(power, accuracy) > budget + 2
        ):
            raise ChargenError(
                f"Authored Power and Accuracy must total {budget}, each between -2 and +{budget + 2}."
            )
    elif power or accuracy:
        raise ChargenError("Assist and Dispirit do not use Power or Accuracy tiers.")
    if data.get("domain_mode", "waive") != "waive":
        raise ChargenError("The supported built-in domain mode is waive (remove its surcharge).")
    if data.get("domain") and not signature:
        raise ChargenError("Only a Signature may build in a domain effect.")
    if data.get("assist_stat"):
        stat = get_ruleset().stats.get(data["assist_stat"])
        if action != "assist" or stat is None:
            raise ChargenError("An Assist override must name a known active stat.")
    path = conf.get("RP_CHARGEN_MOVE_VALIDATOR")
    if path:
        try:
            resolve_dotted(path)(dict(data), signature=signature)
        except ValueError as exc:
            raise ChargenError(str(exc)) from None


def _gate():
    if not runtime.get("RP_CHARGEN_MOVES_REVEALED"):
        raise ChargenError("Signature Moves are not available yet.")


def _lock_owner(character):
    from evennia.objects.models import ObjectDB

    ObjectDB.objects.select_for_update().get(pk=character.pk)


def library(character, *, equipped=False):
    from evennia_rp_chargen.models import SignatureMove

    rows = SignatureMove.objects.filter(character_id=character.pk, archived=False)
    if equipped:
        rows = rows.filter(equipped_order__isnull=False)
    return rows.order_by("equipped_order", "name", "pk")


def find(character, key):
    from evennia_rp_chargen.models import SignatureMove

    row = SignatureMove.objects.filter(character_id=character.pk, key=key, archived=False).first()
    if row is None:
        raise ChargenError("No such Signature in your library.")
    return row


@transaction.atomic
def create(character, name, *, by=None, **definition):
    from evennia_rp_chargen.models import SignatureMove

    _gate()
    _lock_owner(character)
    if library(character).count() >= conf.get("RP_CHARGEN_MOVE_LIBRARY_LIMIT"):
        raise ChargenError("Your Signature library is full. Archive an unused move first.")
    key = slugify(name)
    if not key or len(key) > 64 or not name.strip() or len(name) > 80:
        raise ChargenError("Choose a name of 1 to 80 characters with a usable short key.")
    if SignatureMove.objects.filter(character_id=character.pk, key=key).exists():
        raise ChargenError("That Signature key already exists, including archived moves.")
    action = definition.get("action", "attack")
    if set(definition) - {
        "action",
        "wording",
        "power",
        "accuracy",
        "element",
        "effects",
        "domain",
        "domain_mode",
        "assist_stat",
    }:
        raise ChargenError("Unknown Signature field.")
    data = {
        "action": action,
        "power": 2 if action in ("attack", "spell") else 0,
        "accuracy": 0,
        **definition,
    }
    validate_definition(data)
    row = SignatureMove(character=character, key=key, name=name.strip(), **data)
    try:
        row.full_clean()
    except ValidationError as exc:
        raise ChargenError(" ".join(exc.messages)) from None
    row.save()
    return row


@transaction.atomic
def edit(character, key, *, by=None, expected_revision=None, **changes):
    _gate()
    _lock_owner(character)
    row = find(character, key)
    if expected_revision is not None and row.revision != expected_revision:
        raise ChargenError(
            "That Signature changed since you started the draft. Cancel and edit it again."
        )
    allowed = {
        "name",
        "action",
        "wording",
        "power",
        "accuracy",
        "element",
        "effects",
        "domain",
        "domain_mode",
        "assist_stat",
    }
    if set(changes) - allowed:
        raise ChargenError("Unknown Signature field.")
    if row.equipped_order is not None:
        _guard(character, by)
    for field, value in changes.items():
        setattr(row, field, value)
    validate_definition(row.definition())
    row.revision += 1
    try:
        row.full_clean()
    except ValidationError as exc:
        raise ChargenError(" ".join(exc.messages)) from None
    row.save()
    return row


def _guard(character, by):
    if locks.scope_locked(character, conf.LOADOUT):
        raise ChargenError(locks.locked_message(character))
    guards.check(guards.BuildChange(character, guards.SIGNATURE, by=by))


@transaction.atomic
def equip(character, key, *, equipped=True, by=None):
    _gate()
    _lock_owner(character)
    row = find(character, key)
    _guard(character, by)
    if equipped:
        validate_definition(row.definition())
        others = list(library(character, equipped=True).exclude(pk=row.pk))
        if len(others) >= conf.get("RP_CHARGEN_MOVE_EQUIPPED_LIMIT"):
            raise ChargenError("Your equipped Signature loadout is full.")
        row.equipped_order = max((other.equipped_order for other in others), default=-1) + 1
    else:
        row.equipped_order = None
    row.save(update_fields=["equipped_order", "updated_at"])
    return row


@transaction.atomic
def archive(character, key, *, by=None):
    _gate()
    _lock_owner(character)
    row = find(character, key)
    if row.equipped_order is not None:
        _guard(character, by)
    row.archived, row.equipped_order = True, None
    row.save(update_fields=["archived", "equipped_order", "updated_at"])
