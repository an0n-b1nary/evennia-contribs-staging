# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Sheet changes, with every policy applied: the API commands (and games) call.

Each function raises `ChargenError` with a message fit to show the player when
a change isn't allowed. The rules:

- **Rungs** are chosen while the sheet is a draft, within the allocation
  (`allocation`). Once finalized, only staff change them.
- **Edge and weakness** stay player-managed after finalising, within the pip
  policy (`pips`), but not while the build is locked (`locks`).
- **Finalising** needs every stat set and nothing the allocation or pip
  policy objects to. The player does it; staff review is optional unless
  `RP_CHARGEN_REQUIRE_APPROVAL` is set.
- **Guards** (`guards`) other apps connect may refuse any rating change, staff
  edits included, after these rules pass and before anything is written.
"""

from __future__ import annotations

from django.utils import timezone

from evennia_rp_chargen import conf, guards, locks
from evennia_rp_chargen.allocation import AllocationReport, get_allocation
from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.pips import PipPolicy
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_rules.ruleset import Ruleset, StatDef, get_ruleset
from evennia_rp_rules.scales import Rating


class ChargenError(Exception):
    """A sheet change isn't allowed. The message is fit to show the player."""


def get_build(character) -> CharacterBuild | None:
    return CharacterBuild.objects.filter(character_id=character.id).first()


def ensure_build(character) -> CharacterBuild:
    build, _ = CharacterBuild.objects.get_or_create(
        character_id=character.id, defaults={"character_name": character.key}
    )
    return build


def find_stat(text: str, ruleset: Ruleset | None = None) -> StatDef:
    try:
        return (ruleset or get_ruleset()).find_stat(text)
    except LookupError as exc:
        raise ChargenError(str(exc)) from None


def allocation_report(character) -> AllocationReport:
    ruleset = get_ruleset()
    return get_allocation().check(StatHandler(character, ruleset).ratings(), ruleset)


def _account(by):
    """The account behind `by` (an account, or a puppeted character)."""
    if by is None:
        return None
    from evennia.accounts.models import AccountDB

    return by if isinstance(by, AccountDB) else getattr(by, "account", None)


# ---------------------------------------------------------------------------
# Rungs (draft)
# ---------------------------------------------------------------------------


def set_stat(character, stat_text: str, rung_text: str) -> tuple[Rating, AllocationReport]:
    """Choose a stat's rung on a draft sheet, keeping its pips.

    Returns the new rating and the allocation report after the change.
    """
    build = ensure_build(character)
    if not build.is_draft:
        raise ChargenError("Your stats are final. Ask staff if something needs changing.")
    ruleset = get_ruleset()
    stat = find_stat(stat_text, ruleset)
    try:
        parsed = stat.scale.parse(rung_text)
    except ValueError as exc:
        raise ChargenError(str(exc)) from None
    if parsed.edge or parsed.weakness:
        raise ChargenError(
            f"+stats only picks the {stat.scale.name.lower()}; set "
            f"{conf.get('RP_CHARGEN_PIP_NOUN')} and {conf.get('RP_CHARGEN_WEAKNESS_NOUN')} "
            "with +pips."
        )
    handler = StatHandler(character, ruleset)
    current = handler.get(stat)
    new = stat.scale.rating(
        parsed.rung, current.edge if current else 0, current.weakness if current else 0
    )
    ratings = handler.ratings()
    ratings[stat.key] = new
    report = get_allocation().check(ratings, ruleset)
    if report.errors:
        raise ChargenError(" ".join(report.errors))
    guards.check(guards.BuildChange(character, guards.RATING, stat=stat, before=current, after=new))
    handler.set(stat, new)
    build.allocation_spent = report.spent
    build.save(update_fields=["allocation_spent", "updated_at"])
    return new, report


def clear_stat(character, stat_text: str) -> AllocationReport:
    """Unset a stat on a draft sheet (pips go with it)."""
    build = ensure_build(character)
    if not build.is_draft:
        raise ChargenError("Your stats are final. Ask staff if something needs changing.")
    ruleset = get_ruleset()
    handler = StatHandler(character, ruleset)
    stat = find_stat(stat_text, ruleset)
    guards.check(guards.BuildChange(character, guards.RATING, stat=stat, before=handler.get(stat)))
    handler.clear(stat)
    report = get_allocation().check(handler.ratings(), ruleset)
    build.allocation_spent = report.spent
    build.save(update_fields=["allocation_spent", "updated_at"])
    return report


# ---------------------------------------------------------------------------
# Pips (any time the build isn't locked)
# ---------------------------------------------------------------------------


def _check_pips_changeable(character) -> None:
    build = get_build(character)
    if build is None:
        raise ChargenError("You don't have a character sheet yet. Start one with +stats.")
    if not build.is_draft and locks.scope_locked(character, conf.PIPS):
        raise ChargenError(locks.locked_message())


def _change_pips(character, stat_text: str, **pips) -> Rating:
    _check_pips_changeable(character)
    ruleset = get_ruleset()
    stat = find_stat(stat_text, ruleset)
    handler = StatHandler(character, ruleset)
    current = handler.get(stat)
    if current is None:
        raise ChargenError(f"Give {stat.name} a {stat.scale.name.lower()} first, with +stats.")
    policy = PipPolicy.from_settings()
    for kind, count in pips.items():
        if kind == "edge":
            limit, noun = policy.edge_limit(stat.scale), conf.get("RP_CHARGEN_PIP_NOUN")
        else:
            limit, noun = policy.weakness_limit(stat.scale), conf.get("RP_CHARGEN_WEAKNESS_NOUN")
        if not isinstance(count, int) or count < 0:
            raise ChargenError(f"Give a whole number of {noun}, 0 or more.")
        if count > limit:
            raise ChargenError(f"{stat.name} may carry at most {limit} {noun}, not {count}.")
    new = current.with_pips(**pips)
    ratings = handler.ratings()
    before = set(policy.errors(ratings, ruleset))
    ratings[stat.key] = new
    # Refuse only problems this change creates, so a policy tightened after the
    # fact doesn't block a player from moving pips towards compliance.
    created = [e for e in policy.errors(ratings, ruleset) if e not in before]
    if created:
        raise ChargenError(" ".join(created))
    guards.check(guards.BuildChange(character, guards.RATING, stat=stat, before=current, after=new))
    return handler.set(stat, new)


def set_edge(character, stat_text: str, count: int) -> Rating:
    return _change_pips(character, stat_text, edge=count)


def set_weakness(character, stat_text: str, count: int) -> Rating:
    return _change_pips(character, stat_text, weakness=count)


def clear_edge(character, stat_text: str | None = None) -> list[Rating]:
    """Remove the edge from one stat, or from every stat."""
    ruleset = get_ruleset()
    if stat_text is not None:
        return [set_edge(character, stat_text, 0)]
    _check_pips_changeable(character)
    handler = StatHandler(character, ruleset)
    keys = [key for key, rating in handler.ratings().items() if rating is not None and rating.edge]
    # Ask the guards about every stat before clearing any, so a refusal leaves
    # the whole sheet as it was rather than half cleared.
    refused = [
        message
        for key in keys
        for message in guards.refusals(
            guards.BuildChange(
                character,
                guards.RATING,
                stat=find_stat(key, ruleset),
                before=handler.get(key),
                after=handler.get(key).with_pips(edge=0),
            )
        )
    ]
    if refused:
        raise ChargenError(" ".join(dict.fromkeys(refused)))
    return [set_edge(character, key, 0) for key in keys]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def finalize(character) -> CharacterBuild:
    """Finish a draft. Refuses, listing everything left to do, if it isn't ready."""
    build = ensure_build(character)
    if not build.is_draft:
        raise ChargenError("Your sheet is already finalized.")
    ruleset = get_ruleset()
    handler = StatHandler(character, ruleset)
    ratings = handler.ratings()
    report = get_allocation().check(ratings, ruleset)
    problems = [
        *handler.problems(),
        *report.errors,
        *report.todo,
        *PipPolicy.from_settings().errors(ratings, ruleset),
    ]
    if problems:
        raise ChargenError("Not yet: " + " ".join(problems))
    build.status = CharacterBuild.Status.FINALIZED
    build.finalized_at = timezone.now()
    build.allocation_spent = report.spent
    build.character_name = character.key
    build.save()
    return build


def approve(character, *, by=None, note: str = "") -> CharacterBuild:
    """Staff: approve a finalized sheet."""
    build = get_build(character)
    if build is None or build.status != CharacterBuild.Status.FINALIZED:
        raise ChargenError(f"{character.key} has no finalized sheet awaiting approval.")
    build.status = CharacterBuild.Status.APPROVED
    build.reviewed_by = _account(by)
    build.reviewed_at = timezone.now()
    build.review_note = note[:500]
    build.save()
    return build


def reopen(character, *, by=None, note: str = "") -> CharacterBuild:
    """Staff: send a sheet back to draft so its rungs can change again."""
    build = get_build(character)
    if build is None or build.is_draft:
        raise ChargenError(f"{character.key}'s sheet is already a draft.")
    build.status = CharacterBuild.Status.DRAFT
    build.reviewed_by = _account(by)
    build.reviewed_at = timezone.now()
    build.review_note = note[:500]
    build.save()
    locks.release(character, "your sheet was reopened")
    return build


def staff_set_stat(
    character, stat_text: str, rating_text: str, *, by=None
) -> tuple[Rating, list[str]]:
    """Staff: set a stat's full rating (rung and pips), bypassing policy.

    Returns the rating and any policy problems it creates, as warnings. Guards
    still apply: a change one refuses raises `ChargenError`.
    """
    ensure_build(character)
    ruleset = get_ruleset()
    stat = find_stat(stat_text, ruleset)
    try:
        rating = stat.scale.parse(rating_text)
    except ValueError as exc:
        raise ChargenError(str(exc)) from None
    handler = StatHandler(character, ruleset)
    guards.check(
        guards.BuildChange(
            character, guards.RATING, stat=stat, before=handler.get(stat), after=rating, by=by
        )
    )
    handler.set(stat, rating)
    ratings = handler.ratings()
    warnings = [
        *get_allocation().check(ratings, ruleset).errors,
        *PipPolicy.from_settings().errors(ratings, ruleset),
    ]
    return rating, warnings


__all__ = [
    "ChargenError",
    "allocation_report",
    "approve",
    "clear_edge",
    "clear_stat",
    "ensure_build",
    "finalize",
    "find_stat",
    "get_build",
    "reopen",
    "set_edge",
    "set_stat",
    "set_weakness",
    "staff_set_stat",
]
