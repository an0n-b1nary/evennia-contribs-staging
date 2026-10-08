# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Rendering a character sheet as text.

Only the character's owner and staff ever see a sheet, so it shows both pip
runs (`B +++ -`), keeping a weakness taken for flavour visible. It never shows
scores. Allocation points appear only while the sheet is a draft.
"""

from __future__ import annotations

from evennia_rp_chargen import conf, locks
from evennia_rp_chargen.allocation import get_allocation
from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.pips import PipPolicy
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_rules.ruleset import get_ruleset


def _grouped(ruleset):
    groups: dict[str, list] = {}
    for stat in ruleset.stats.values():
        groups.setdefault(stat.category, []).append(stat)
    return groups


def stat_lines(character) -> list[str]:
    """One line per stat, grouped by category: `  Charisma    B +++ -`."""
    ruleset = get_ruleset()
    handler = StatHandler(character, ruleset)
    width = max((len(stat.name) for stat in ruleset.stats.values()), default=0)
    lines = []
    for category, stats in _grouped(ruleset).items():
        indent = "  "
        if category:
            lines.append(f" |w{category.replace('_', ' ').title()}|n")
            indent = "    "
        for stat in stats:
            rating = handler.get(stat)
            shown = rating.display() if rating is not None else "|x-|n"
            lines.append(f"{indent}{stat.name:<{width}}  {shown}")
    return lines


def ability_lines(character, build=None) -> list[str]:
    """Abilities, flaws, loadout use and what's left to spend."""
    from evennia_rp_chargen import abilities

    copies = abilities.owned(character)
    lines = []
    equipped = [c for c in copies if c.equipped and not c.ability.is_flaw]
    spare = [c for c in copies if not c.equipped and not c.ability.is_flaw]
    flaws = [c for c in copies if c.ability.is_flaw]

    def name(copy):
        level = f" {copy.level}" if copy.ability.max_level > 1 else ""
        return f"{copy.display_name}{level}"

    if copies:
        lines.append("")
    if equipped:
        lines.append(" |wEquipped:|n " + ", ".join(name(c) for c in equipped))
    if spare:
        lines.append(" |wNot equipped:|n " + ", ".join(name(c) for c in spare))
    if flaws:
        lines.append(" |wFlaws:|n " + ", ".join(name(c) for c in flaws))
    budget = abilities.loadout_budget()
    unit = conf.get("RP_CHARGEN_LOADOUT_UNIT")
    noun = conf.get("RP_CHARGEN_LOADOUT_NOUN").capitalize()
    used = abilities.loadout_used(character)
    if budget is not None:
        lines.append(f" {noun}: {used} of {budget} {unit} used.")
        if used > budget:
            lines.append(
                " |yOver budget: existing abilities stay equipped. Unequip before adding more.|n"
            )
    if build is not None and build.allowance_total:
        allowance = conf.get("RP_CHARGEN_ALLOWANCE_NOUN").capitalize()
        lines.append(
            f" {allowance}: {abilities.format_amount(build.allowance_left)} of "
            f"{abilities.format_amount(build.allowance_total)} left."
        )
    return lines


def render_sheet(character, *, staff: bool = False) -> str:
    """The full sheet. `staff` adds the review trail and data problems."""
    ruleset = get_ruleset()
    build = CharacterBuild.objects.filter(character_id=character.id).first()
    status = build.get_status_display() if build else "Not started"
    lines = [f"|w{character.key}|n  |x({status})|n", *stat_lines(character)]

    handler = StatHandler(character, ruleset)
    ratings = handler.ratings()
    policy = PipPolicy.from_settings()
    edge_noun = conf.get("RP_CHARGEN_PIP_NOUN")
    spent = policy.edge_spent(ratings)
    edge = f"{edge_noun.capitalize()}: {spent}"
    if policy.edge_budget is not None:
        edge += f" of {policy.edge_budget} used"
    weakness = sum(r.weakness for r in ratings.values() if r is not None)
    lines.append("")
    lines.append(f" {edge}.  {conf.get('RP_CHARGEN_WEAKNESS_NOUN').capitalize()}: {weakness}.")

    if build is None or build.is_draft:
        report = get_allocation().check(ratings, ruleset)
        if report.summary:
            lines.append(f" {report.summary[0].upper()}{report.summary[1:]}.")
        todo = [*report.errors, *report.todo, *policy.errors(ratings, ruleset)]
        if todo:
            lines.append(" |yTo do:|n " + " ".join(todo))
        else:
            lines.append(" Ready: +stats/finalize when you're happy with it.")
    else:
        state = locks.state(character)
        things = conf.locked_things()
        if state.locked:
            lines.append(f" {things.capitalize()}: |ylocked|n ({state.reason or 'locked'}).")
        else:
            lines.append(f" {things.capitalize()}: unlocked.")

    lines.extend(ability_lines(character, build))

    if staff:
        if build is not None and build.reviewed_at:
            reviewer = build.reviewed_by.key if build.reviewed_by else "?"
            note = f": {build.review_note}" if build.review_note else ""
            lines.append(f" |xReviewed by {reviewer} {build.reviewed_at:%Y-%m-%d}{note}|n")
        for problem in handler.problems():
            lines.append(f" |rData problem:|n {problem}")
    return "\n".join(lines)


__all__ = ["render_sheet", "stat_lines"]
