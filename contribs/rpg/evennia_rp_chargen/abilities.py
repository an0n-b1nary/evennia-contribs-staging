# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ability and flaw services: acquiring, upgrading, equipping, and staff grants.

Every function raises `ChargenError` with a message fit to show the player.

- **Buying** (`acquire`, `upgrade`) pays from the sheet's starting allowance
  first, then from the XP ledger (`ledger`). Each purchase writes an
  `AbilityTransaction` saying how it was funded, all in one transaction.
- **Equipping** keeps the loadout within `RP_CHARGEN_LOADOUT_BUDGET` and is
  frozen while the build is locked (the `loadout` lock scope).
- **Flaws** are free, self-service, always equipped while held, and refund
  nothing. Staff-only flaws (acquisition `staff`) can't be shed by players.
- **Staff** grant any ability at any level for free, revoke with an optional
  refund, and set a sheet's starting allowance.
- **Guards** (`guards`) other apps connect may refuse any of these changes,
  staff ones included, after the rules above pass and before anything is
  written or paid. Auto-equipping skips quietly when a guard objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from evennia_rp_chargen import conf, guards, locks
from evennia_rp_chargen.catalog import find_ability
from evennia_rp_chargen.ledger import InsufficientXP, LedgerUnavailable, get_ledger
from evennia_rp_chargen.models import (
    AbilityDefinition,
    AbilityTransaction,
    CharacterAbility,
    CharacterBuild,
)
from evennia_rp_chargen.services import ChargenError, _account, ensure_build
from evennia_rp_chargen.vocabulary import DBVocabulary, ensure_tag

Acquisition = AbilityDefinition.Acquisition
Kind = AbilityTransaction.Kind


@dataclass(frozen=True)
class Payment:
    allowance: Decimal = Decimal(0)
    xp: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return self.allowance + self.xp

    def describe(self) -> str:
        noun = conf.get("RP_CHARGEN_ALLOWANCE_NOUN")
        parts = []
        if self.allowance:
            parts.append(f"{format_amount(self.allowance)} {noun}")
        if self.xp:
            parts.append(f"{format_amount(self.xp)} XP")
        return " and ".join(parts) or "nothing"


def format_amount(amount: Decimal) -> str:
    """`3`, `2.5`: an amount without trailing zeros."""
    return f"{Decimal(amount).normalize():f}"


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def _ability(text: str, *, include_archived: bool = False) -> AbilityDefinition:
    try:
        return find_ability(text, include_archived=include_archived)
    except LookupError as exc:
        raise ChargenError(str(exc)) from None


def _tag(ability: AbilityDefinition, tag_text: str | None):
    """The `TagDefinition` a template copy is for (None for a plain ability)."""
    if not ability.is_template:
        if tag_text:
            raise ChargenError(f"{ability.name} isn't chosen per {ability.tag_kind or 'tag'}.")
        return None
    if not tag_text:
        raise ChargenError(
            f"Which {ability.tag_kind}? For example: {ability.name}: <{ability.tag_kind}>"
        )
    try:
        tag = DBVocabulary().find(tag_text, kind=ability.tag_kind)
    except LookupError as exc:
        raise ChargenError(str(exc)) from None
    return ensure_tag(tag)


def owned(character) -> list[CharacterAbility]:
    return list(
        CharacterAbility.objects.filter(character_id=character.id)
        .select_related("ability", "tag")
        .order_by("ability__is_flaw", "ability__name", "tag__name")
    )


def find_owned(character, ability_text: str, tag_text: str | None = None) -> CharacterAbility:
    """One of the character's copies, by ability and (for templates) tag.

    A template's tag may be left out when the character holds only one copy.
    """
    ability = _ability(ability_text, include_archived=True)
    copies = [c for c in owned(character) if c.ability_id == ability.id]
    if ability.is_template and not tag_text:
        if len(copies) == 1:
            return copies[0]
        if copies:
            choices = ", ".join(c.tag.name for c in copies)
            raise ChargenError(f"Which {ability.name}? You have: {choices}.")
    else:
        tag = _tag(ability, tag_text)
        copies = [c for c in copies if c.tag_id == (tag.id if tag else None)]
        if copies:
            return copies[0]
    raise ChargenError(
        f"You don't have {ability.display_name(None)}{f': {tag_text}' if tag_text else ''}."
    )


# ---------------------------------------------------------------------------
# Loadout
# ---------------------------------------------------------------------------


def loadout_used(character) -> int:
    return sum(copy.budget_cost for copy in owned(character) if copy.equipped)


def loadout_budget() -> int | None:
    return conf.get("RP_CHARGEN_LOADOUT_BUDGET")


def _check_unlocked(character) -> None:
    build = ensure_build(character)
    if not build.is_draft and locks.scope_locked(character, conf.LOADOUT):
        raise ChargenError(locks.locked_message())


def _change(character, kind, copy=None, **fields) -> guards.BuildChange:
    """A `BuildChange` for an ability change; `copy` fills in ability, tag and level."""
    if copy is not None:
        fields = {"ability": copy.ability, "tag": copy.tag, "level": copy.level, **fields}
    return guards.BuildChange(character, kind, copy=copy, **fields)


def _fits(character, extra: int) -> bool:
    budget = loadout_budget()
    return budget is None or loadout_used(character) + extra <= budget


def _budget_error(character, copy: CharacterAbility) -> ChargenError:
    unit = conf.get("RP_CHARGEN_LOADOUT_UNIT")
    budget = loadout_budget()
    used = loadout_used(character)
    return ChargenError(
        f"{copy.display_name} needs {copy.budget_cost} {unit}; you have "
        f"{budget - used} of {budget} free. Unequip something first."
    )


def equip(character, ability_text: str, tag_text: str | None = None) -> CharacterAbility:
    copy = find_owned(character, ability_text, tag_text)
    if copy.equipped:
        raise ChargenError(f"{copy.display_name} is already equipped.")
    _check_unlocked(character)
    if not _fits(character, copy.budget_cost):
        raise _budget_error(character, copy)
    guards.check(_change(character, guards.EQUIP, copy))
    copy.equipped = True
    copy.save(update_fields=["equipped", "updated_at"])
    return copy


def unequip(character, ability_text: str, tag_text: str | None = None) -> CharacterAbility:
    copy = find_owned(character, ability_text, tag_text)
    if copy.ability.is_flaw:
        raise ChargenError("Flaws stay in effect while you have them.")
    if not copy.equipped:
        raise ChargenError(f"{copy.display_name} isn't equipped.")
    _check_unlocked(character)
    guards.check(_change(character, guards.UNEQUIP, copy))
    copy.equipped = False
    copy.save(update_fields=["equipped", "updated_at"])
    return copy


# ---------------------------------------------------------------------------
# Paying
# ---------------------------------------------------------------------------


def balance(character) -> tuple[Decimal, Decimal | None]:
    """(allowance left, XP balance or None when there's no ledger)."""
    build = ensure_build(character)
    ledger = get_ledger()
    xp = None if getattr(ledger, "available", True) is False else ledger.balance(character)
    return build.allowance_left, xp


def _pay(character, build: CharacterBuild, amount: Decimal, tx: AbilityTransaction) -> Payment:
    """Spend `amount`, allowance first. Call inside `transaction.atomic()`."""
    noun = conf.get("RP_CHARGEN_ALLOWANCE_NOUN")
    left = build.allowance_left
    from_allowance = min(left, amount)
    from_xp = amount - from_allowance
    if from_xp > 0:
        ref = f"rp_chargen.tx.{tx.pk}"
        try:
            get_ledger().spend(character, from_xp, ref_key=ref, reason=tx.ability_name)
        except LedgerUnavailable:
            raise ChargenError(
                f"That costs {format_amount(amount)}, and you have {format_amount(left)} {noun} left. "
                "XP spending isn't available in this game."
            ) from None
        except InsufficientXP:
            raise ChargenError(
                f"That costs {format_amount(amount)}: your {format_amount(left)} {noun} and your XP aren't enough."
            ) from None
        tx.ledger_ref = ref
    if from_allowance:
        # Conditional update: a concurrent spend can't take the allowance below zero.
        updated = CharacterBuild.objects.filter(
            pk=build.pk, allowance_spent=build.allowance_spent
        ).update(allowance_spent=F("allowance_spent") + from_allowance)
        if updated != 1:
            raise ChargenError("Your allowance changed while you were spending it; try again.")
    tx.allowance_amount, tx.xp_amount = from_allowance, from_xp
    tx.save()
    return Payment(from_allowance, from_xp)


def _record(character, ability, tag, kind, *, level_from=0, level_to=0, by=None, note=""):
    return AbilityTransaction.objects.create(
        character_id=character.id,
        character_name=character.key,
        ability=ability,
        ability_name=ability.display_name(tag),
        tag_key=tag.key if tag else "",
        kind=kind,
        level_from=level_from,
        level_to=level_to,
        actor=_account(by),
        note=note[:500],
    )


# ---------------------------------------------------------------------------
# Buying
# ---------------------------------------------------------------------------


def acquire(character, ability_text: str, tag_text: str | None = None, *, by=None):
    """Buy an ability at level 1. Equips it too, if the loadout allows.

    Returns:
        `(copy, payment)`.
    """
    ability = _ability(ability_text)
    if ability.is_flaw:
        raise ChargenError(f"{ability.name} is a flaw; take it with +abilities/flaw.")
    if ability.acquisition != Acquisition.XP:
        raise ChargenError(f"{ability.name} is granted by staff, not bought.")
    tag = _tag(ability, tag_text)
    if CharacterAbility.objects.filter(
        character_id=character.id, ability=ability, tag=tag
    ).exists():
        raise ChargenError(f"You already have {ability.display_name(tag)}.")
    build = ensure_build(character)
    guards.check(_change(character, guards.ACQUIRE, ability=ability, tag=tag, level=1, by=by))
    with transaction.atomic():
        tx = _record(character, ability, tag, Kind.ACQUIRE, level_to=1, by=by)
        payment = _pay(character, build, ability.xp_cost, tx)
        copy = CharacterAbility.objects.create(character_id=character.id, ability=ability, tag=tag)
        _auto_equip(character, copy)
    return copy, payment


def _auto_equip(character, copy: CharacterAbility) -> None:
    build = ensure_build(character)
    locked = not build.is_draft and locks.scope_locked(character, conf.LOADOUT)
    if (
        not locked
        and _fits(character, copy.budget_cost)
        and not guards.refusals(_change(character, guards.EQUIP, copy))
    ):
        copy.equipped = True
        copy.save(update_fields=["equipped", "updated_at"])


def next_upgrade_cost(copy: CharacterAbility) -> Decimal | None:
    """XP for the next level, or None at the top."""
    if copy.level >= copy.ability.max_level:
        return None
    return conf.upgrade_cost(copy.level)


def upgrade(character, ability_text: str, tag_text: str | None = None, *, by=None):
    """Raise a bought ability one level. Returns `(copy, payment)`."""
    copy = find_owned(character, ability_text, tag_text)
    ability = copy.ability
    if ability.is_flaw or ability.acquisition != Acquisition.XP:
        raise ChargenError(f"{copy.display_name} can't be upgraded with XP.")
    cost = next_upgrade_cost(copy)
    if cost is None:
        raise ChargenError(
            f"{copy.display_name} is already at its highest level ({ability.max_level})."
        )
    build = ensure_build(character)
    guards.check(_change(character, guards.UPGRADE, copy, level=copy.level + 1, by=by))
    with transaction.atomic():
        tx = _record(
            character,
            ability,
            copy.tag,
            Kind.UPGRADE,
            level_from=copy.level,
            level_to=copy.level + 1,
            by=by,
        )
        payment = _pay(character, build, cost, tx)
        # Do not charge twice for the same level when two commands read it together.
        updated = CharacterAbility.objects.filter(pk=copy.pk, level=copy.level).update(
            level=F("level") + 1, updated_at=timezone.now()
        )
        if updated != 1:
            raise ChargenError("Your ability changed while you were upgrading it; try again.")
        copy.refresh_from_db()
    return copy, payment


# ---------------------------------------------------------------------------
# Flaws
# ---------------------------------------------------------------------------


def take_flaw(character, flaw_text: str, tag_text: str | None = None) -> CharacterAbility:
    ability = _ability(flaw_text)
    if not ability.is_flaw:
        raise ChargenError(f"{ability.name} isn't a flaw.")
    if ability.acquisition != Acquisition.FREE:
        raise ChargenError(f"{ability.name} is given by staff, not taken.")
    tag = _tag(ability, tag_text)
    if CharacterAbility.objects.filter(
        character_id=character.id, ability=ability, tag=tag
    ).exists():
        raise ChargenError(f"You already have {ability.display_name(tag)}.")
    _check_unlocked(character)
    guards.check(_change(character, guards.TAKE_FLAW, ability=ability, tag=tag, level=1))
    with transaction.atomic():
        _record(character, ability, tag, Kind.FLAW_ADD, level_to=1)
        return CharacterAbility.objects.create(
            character_id=character.id, ability=ability, tag=tag, equipped=True
        )


def remove_flaw(character, flaw_text: str, tag_text: str | None = None) -> str:
    copy = find_owned(character, flaw_text, tag_text)
    if not copy.ability.is_flaw:
        raise ChargenError(f"{copy.display_name} isn't a flaw.")
    if copy.ability.acquisition != Acquisition.FREE:
        raise ChargenError(f"{copy.display_name} was given by staff; ask them about it.")
    _check_unlocked(character)
    guards.check(_change(character, guards.REMOVE_FLAW, copy, level=0))
    name = copy.display_name
    with transaction.atomic():
        _record(character, copy.ability, copy.tag, Kind.FLAW_REMOVE, level_from=copy.level)
        copy.delete()
    return name


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


def grant(character, ability_text: str, tag_text: str | None = None, *, level: int = 1, by=None):
    """Give an ability (or flaw) at `level` for free, or move an existing copy to `level`."""
    ability = _ability(ability_text, include_archived=True)
    if not 1 <= level <= ability.max_level:
        raise ChargenError(f"{ability.name} goes from level 1 to {ability.max_level}.")
    tag = _tag(ability, tag_text)
    ensure_build(character)
    copy = CharacterAbility.objects.filter(
        character_id=character.id, ability=ability, tag=tag
    ).first()
    guards.check(
        _change(character, guards.GRANT, copy, ability=ability, tag=tag, level=level, by=by)
    )
    with transaction.atomic():
        before = copy.level if copy else 0
        if copy is None:
            copy = CharacterAbility.objects.create(
                character_id=character.id,
                ability=ability,
                tag=tag,
                level=level,
                equipped=ability.is_flaw,
            )
        else:
            copy.level = level
            copy.save(update_fields=["level", "updated_at"])
        _record(character, ability, tag, Kind.GRANT, level_from=before, level_to=level, by=by)
    if not ability.is_flaw and not copy.equipped:
        _auto_equip(character, copy)
    return copy


def revoke(character, ability_text: str, tag_text: str | None = None, *, refund=False, by=None):
    """Take a copy away. With `refund`, return what was paid for it.

    Returns:
        `(name, refunded Payment, unrefunded XP)`. XP can't be refunded without
        a ledger; that amount is reported rather than lost silently.
    """
    copy = find_owned(character, ability_text, tag_text)
    guards.check(_change(character, guards.REVOKE, copy, level=0, by=by))
    ability, tag = copy.ability, copy.tag
    history = AbilityTransaction.objects.filter(
        character_id=character.id, ability=ability, tag_key=tag.key if tag else ""
    )
    # Only what was paid for this copy: purchases since the last time one was taken away.
    last_removal = history.filter(kind__in=(Kind.REVOKE, Kind.FLAW_REMOVE)).order_by("-id").first()
    paid = history.filter(kind__in=(Kind.ACQUIRE, Kind.UPGRADE))
    if last_removal is not None:
        paid = paid.filter(id__gt=last_removal.id)
    allowance = sum((t.allowance_amount for t in paid), Decimal(0)) if refund else Decimal(0)
    xp_refunded, xp_kept = Decimal(0), Decimal(0)
    with transaction.atomic():
        if refund:
            ledger = get_ledger()
            for t in paid.exclude(ledger_ref="").filter(xp_amount__gt=0):
                try:
                    xp_refunded += Decimal(ledger.refund(character, ref_key=t.ledger_ref))
                except LedgerUnavailable:
                    xp_kept += t.xp_amount
            if allowance:
                CharacterBuild.objects.filter(character_id=character.id).update(
                    allowance_spent=F("allowance_spent") - allowance
                )
        tx = _record(character, ability, tag, Kind.REVOKE, level_from=copy.level, by=by)
        tx.allowance_amount, tx.xp_amount = -allowance, -xp_refunded
        tx.save()
        name = copy.display_name
        copy.delete()
    return name, Payment(allowance, xp_refunded), xp_kept


def set_allowance(character, amount: Decimal | None, *, by=None) -> CharacterBuild:
    """Set a sheet's starting allowance (`None`: back to the game default)."""
    build = ensure_build(character)
    if amount is not None and amount < 0:
        raise ChargenError("The allowance can't be negative.")
    build.starting_allowance = amount
    build.save(update_fields=["starting_allowance", "updated_at"])
    AbilityTransaction.objects.create(
        character_id=character.id,
        character_name=character.key,
        kind=Kind.ALLOWANCE,
        actor=_account(by),
        note=f"allowance set to {'default' if amount is None else format_amount(amount)}",
    )
    return build


__all__ = [
    "Payment",
    "acquire",
    "balance",
    "equip",
    "find_owned",
    "format_amount",
    "grant",
    "loadout_budget",
    "loadout_used",
    "next_upgrade_cost",
    "owned",
    "remove_flaw",
    "revoke",
    "set_allowance",
    "take_flaw",
    "unequip",
    "upgrade",
]
