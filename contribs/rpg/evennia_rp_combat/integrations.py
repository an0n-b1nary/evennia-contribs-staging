# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional chargen adapter; all imports occur after registry checks."""

from .data import CombatError, Move


def connect_chargen():
    from evennia_rp_chargen.guards import build_change_requested

    build_change_requested.connect(build_guard, weak=False, dispatch_uid="rp_combat.build_guard")


def build_guard(sender, change, **kwargs):
    from evennia_rp_chargen import guards

    if change.kind == guards.ACQUIRE:
        return None  # Own a new library ability; auto-equip asks separately.
    if (
        change.kind in (guards.GRANT, guards.UPGRADE, guards.REVOKE)
        and change.ability
        and not change.ability.is_flaw
        and (change.copy is None or not change.copy.equipped)
    ):
        return None
    # The coordinator persists this marker independently of chargen's pose/TTL
    # lock. Fading, reload, +unlock and exchange completion cannot clear it.
    state = change.character.attributes.get("build_lock", category="rp_combat", default=None)
    if state and not state.get("correction", False):
        return "Your combat build is frozen. Clear pending exchanges, then use +combat/unlock for an announced correction."
    return None


def validate_move(data, *, signature=True):
    from . import conf

    move = Move.from_dict({**data, "kind": "signature" if signature else "improvised"})
    if move.domain and move.domain not in conf.get("RP_COMBAT_DOMAIN_EFFECTS"):
        raise CombatError("Unknown built-in domain effect.")
    if move.assist_stat:
        roles = conf.get("RP_COMBAT_ROLES")
        active = {roles[key] for key in ("attack", "spell", "dispirit")}
        if move.assist_stat not in active:
            raise CombatError("An Assist override must be an active stat, not a defensive stat.")
    if move.element:
        from evennia_rp_rules.vocabulary import get_vocabulary

        try:
            get_vocabulary().find(move.element, kind=conf.get("RP_COMBAT_ELEMENT_KIND"))
        except LookupError:
            raise CombatError("Unknown move element/style.") from None


def chargen_build(character):
    import json

    from django.db.models import Q
    from evennia_rp_chargen.models import CharacterAbility, CharacterBuild
    from evennia_rp_chargen.moves import library
    from evennia_rp_chargen.subject import ChargenSubject

    from .sources import from_source

    build = CharacterBuild.objects.filter(character_id=character.pk).first()
    if build is None:
        return None
    if not build.is_playable:
        raise CombatError("Finish your sheet and any required approval before combat.")
    copies = CharacterAbility.objects.filter(
        Q(equipped=True) | Q(ability__is_flaw=True), character_id=character.pk
    ).select_related("ability", "tag")
    abilities = tuple(
        (copy.ability.key, copy.tag.key if copy.tag else "", copy.level) for copy in copies
    )
    moves = tuple(
        Move.from_dict({"kind": "signature", **row.snapshot()})
        for row in library(character, equipped=True)
    )
    for move in moves:
        validate_move(move.as_dict())
    from .modifiers import CombatEffect, CombatRule

    kinds = {"combat_bonus": CombatEffect, "combat_rule": CombatRule}
    effects = []
    for copy in copies:
        for spec in copy.ability.effects_for(copy.tag):
            if spec.get("kind") in kinds:
                effect = kinds[spec["kind"]].from_spec(spec, level=copy.level)
                effects.append((copy.modifier_key, json.dumps(effect.frozen())))
    flaws = [
        (copy.ability.key, copy.tag.key if copy.tag else "")
        for copy in copies
        if copy.ability.is_flaw
    ]
    return from_source(
        ChargenSubject(character, build),
        moves=moves,
        abilities=abilities,
        effects=effects,
        flaws=flaws,
    )
