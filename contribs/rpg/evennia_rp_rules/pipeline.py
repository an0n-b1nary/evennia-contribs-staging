# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The phased modifier pipeline.

For each check the pipeline:

1. finds both sides' subjects and base ratings;
2. collects modifiers from, in no particular order, the actor's subject, the
   opponent's subject, every provider in `settings.RP_RULES_MODIFIER_PROVIDERS`
   (dotted paths to `provider(check) -> Iterable[Modifier]`), and the check's
   own `modifiers`;
3. keeps those the viewer may see (estimates only) and that `applies()`;
4. runs BUILD, then PRE_RESOLVE, letting each hooked modifier add entries;
5. folds the entries into each side's effective rating and bonus and hands
   them to the ruleset's resolver (or estimates odds and stops);
6. runs ON_OUTCOME, where modifiers can see the outcome and add notes.

**Order never changes a number.** Within a phase every modifier sees the state
as it was when the phase began, and what they add is merged only once the
phase ends. The fold is a sum (with a max inside each non-stacking group), so
shuffling providers, subjects or modifiers gives identical results, which the
test suite checks by shuffling.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from types import MappingProxyType

from evennia_rp_rules._config import resolve_dotted, setting
from evennia_rp_rules._numbers import to_fraction
from evennia_rp_rules.checks import Check, CheckError, CheckEstimate, CheckResult
from evennia_rp_rules.dice import RandomRoller, Roller
from evennia_rp_rules.modifiers import LedgerEntry, Note
from evennia_rp_rules.phases import (
    ACTOR,
    BUILD,
    CHECK_PHASES,
    ON_OUTCOME,
    OPEN,
    PRE_RESOLVE,
    SIDES,
    STAFF,
    TARGET,
    VISIBILITIES,
    other_side,
    visible_to,
)
from evennia_rp_rules.resolvers import Contest, Resolution
from evennia_rp_rules.ruleset import Ruleset, StatDef, get_ruleset
from evennia_rp_rules.scales import Rating
from evennia_rp_rules.subjects import get_subject, modifiers_of

RESOLVE = "resolve"
ESTIMATE = "estimate"


class ResolutionContext:
    """What a modifier sees and can do, bound to that modifier and its side.

    Attributes:
        mode: `"resolve"` or `"estimate"`.
        check: The check.
        ruleset: The ruleset in use.
        phase: The phase running now (`None` while `applies()` is asked).
        side: The side owning this modifier; `other_side` is the other.
        resolution: The resolver's output, during ON_OUTCOME only.
    """

    def __init__(self, state: _State, modifier, owner: str, staged: list | None = None):
        self._state = state
        self._modifier = modifier
        self._staged = staged
        self.side = owner
        self.other_side = other_side(owner)

    def __repr__(self) -> str:
        return f"<ResolutionContext {self.phase} {self.side} {self._modifier!r}>"

    mode = property(lambda self: self._state.mode)
    check = property(lambda self: self._state.check)
    ruleset = property(lambda self: self._state.ruleset)
    phase = property(lambda self: self._state.phase)
    resolution = property(lambda self: self._state.resolution)

    @property
    def subject(self):
        """The owning side's stat source (`None` for a stated difficulty)."""
        return self._state.subjects[self.side]

    @property
    def stat(self) -> StatDef:
        """The owning side's stat."""
        return self._state.stats[self.side]

    @property
    def tags(self) -> frozenset[str]:
        """The owning side's tags."""
        return self.check.tags_for(self.side)

    def rating(self, side: str | None = None) -> Rating:
        """A side's effective rating as of the start of this phase."""
        return self._state.effective(side or self.side)[0]

    def bonus(self, side: str | None = None) -> Fraction:
        return self._state.effective(side or self.side)[1]

    def score(self, side: str | None = None) -> Fraction:
        rating, bonus = self._state.effective(side or self.side)
        return rating.score() + bonus

    def add(
        self,
        score=0,
        *,
        rung: int = 0,
        side: str | None = None,
        label: str | None = None,
        stack: str | None = None,
        visibility: str | None = None,
    ) -> None:
        """Record a ledger entry: `score` and/or `rung` steps on `side` (default: own side).

        `label`, `stack` and `visibility` default to the modifier's own.

        Raises:
            RuntimeError: Outside BUILD and PRE_RESOLVE, where numbers are settled.
        """
        if self._staged is None or self.phase not in (BUILD, PRE_RESOLVE):
            raise RuntimeError(
                f"modifiers can only change numbers in BUILD or PRE_RESOLVE, not {self.phase}"
            )
        side = side or self.side
        if side not in SIDES:
            raise ValueError(f"side must be one of {list(SIDES)}, got {side!r}")
        if not isinstance(rung, int) or isinstance(rung, bool):
            raise ValueError(f"rung must be a whole number, got {rung!r}")
        mod = self._modifier
        visibility = visibility or getattr(mod, "visibility", None) or OPEN
        _check_visibility(visibility, mod)
        if not self._visible(visibility):
            return
        self._staged.append(
            LedgerEntry(
                key=mod.key,
                label=label or getattr(mod, "label", "") or mod.key,
                owner=self.side,
                side=side,
                phase=self.phase,
                score=to_fraction(score),
                rung=rung,
                visibility=visibility,
                source=getattr(mod, "source", "") or "",
                scope=getattr(mod, "scope", "") or "",
                priority=getattr(mod, "priority", 0) or 0,
                stack=stack if stack is not None else getattr(mod, "stack", None),
            )
        )

    def note(self, text: str, *, visibility: str | None = None) -> None:
        """Attach a note to the result. Allowed in every phase of a resolve."""
        if self._staged is None:
            raise RuntimeError("notes can't be added while applies() is asked")
        mod = self._modifier
        visibility = visibility or getattr(mod, "visibility", None) or OPEN
        _check_visibility(visibility, mod)
        if not self._visible(visibility):
            return
        self._staged.append(Note(mod.key, str(text), self.side, self.phase, visibility))

    def _visible(self, visibility: str) -> bool:
        # An estimate counts only what its viewer may see, even when a visible
        # modifier records a hidden entry.
        state = self._state
        return state.mode != ESTIMATE or visible_to(visibility, self.side, state.viewer)


def _check_visibility(visibility, modifier) -> None:
    if visibility not in VISIBILITIES:
        raise ValueError(
            f"{modifier!r}: visibility must be one of {list(VISIBILITIES)}, got {visibility!r}"
        )


class _State:
    def __init__(self, check: Check, ruleset: Ruleset, mode: str, viewer: str):
        self.check = check
        self.ruleset = ruleset
        self.mode = mode
        self.viewer = viewer
        self.phase: str | None = None
        self.resolution: Resolution | None = None
        self.raw_entries: list[LedgerEntry] = []
        self.ledger: list[LedgerEntry] = []
        self.notes: list[Note] = []
        self.subjects, self.stats, self.ratings = _sides(check, ruleset)
        self._effective: dict[str, tuple[Rating, Fraction]] = {}
        self.commit([])

    def effective(self, side: str) -> tuple[Rating, Fraction]:
        return self._effective[side]

    def commit(self, staged: list) -> None:
        """Merge a phase's additions, then re-settle stacks and refold."""
        self.raw_entries += [item for item in staged if isinstance(item, LedgerEntry)]
        self.notes += [item for item in staged if isinstance(item, Note)]
        self.ledger = _settle(self.raw_entries)
        for side in SIDES:
            applied = [e for e in self.ledger if e.applied and e.side == side]
            steps = sum(e.rung for e in applied)
            base = self.ratings[side]
            rating = base.shifted(steps) if steps else base
            self._effective[side] = (rating, sum((e.score for e in applied), Fraction(0)))


def _settle(entries: list[LedgerEntry]) -> list[LedgerEntry]:
    """Breakdown order, with all but the strongest entry of each stack marked unapplied."""
    ordered = sorted(entries, key=LedgerEntry.sort_key)
    best: dict[tuple[str, str], LedgerEntry] = {}
    for entry in ordered:
        if entry.stack is None:
            continue
        slot = (entry.side, entry.stack)
        current = best.get(slot)
        if current is None or (entry.rung, entry.score) > (current.rung, current.score):
            best[slot] = entry
    settled = []
    for entry in ordered:
        winner = best.get((entry.side, entry.stack)) if entry.stack is not None else None
        if winner is not None and winner is not entry:
            entry = replace(
                entry, applied=False, reason=f"doesn't stack with {winner.label or winner.key}"
            )
        settled.append(entry)
    return settled


def _sides(check: Check, ruleset: Ruleset):
    stats = {ACTOR: _stat(ruleset, check.stat_for(ACTOR))}
    stats[TARGET] = _stat(ruleset, check.stat_for(TARGET))
    subjects = {ACTOR: _subject(check.actor), TARGET: None}
    ratings = {ACTOR: _rating(subjects[ACTOR], check.actor, stats[ACTOR])}
    if check.opposed:
        subjects[TARGET] = _subject(check.opponent)
        ratings[TARGET] = _rating(subjects[TARGET], check.opponent, stats[TARGET])
    else:
        ratings[TARGET] = _difficulty(check.difficulty, stats[TARGET])
    return subjects, stats, ratings


def _stat(ruleset: Ruleset, key: str) -> StatDef:
    stat = ruleset.stats.get(key)
    if stat is None:
        names = ", ".join(sorted(s.name for s in ruleset.stats.values()))
        raise CheckError(f"Unknown stat '{key}'. Choose from: {names}.")
    return stat


def _subject(obj):
    subject = get_subject(obj)
    if subject is None:
        raise CheckError(f"{_name(obj)} has no stats.")
    return subject


def _name(obj) -> str:
    return str(getattr(obj, "key", None) or obj)


def _rating(subject, obj, stat: StatDef) -> Rating:
    rating = subject.get_rating(stat.key)
    if rating is None:
        raise CheckError(f"{_name(obj)} has no {stat.name} rating.")
    if isinstance(rating, str):
        return _difficulty(rating, stat)
    return _on_scale(rating, stat)


def _on_scale(rating: Rating, stat: StatDef) -> Rating:
    """Re-home a rating on the current ruleset's scale (cached ratings may predate a reload)."""
    if rating.scale is stat.scale:
        return rating
    if rating.scale.key != stat.scale.key:
        raise CheckError(
            f"{stat.name} is rated on {stat.scale.name}, not {rating.scale.name} ({rating})."
        )
    try:
        return stat.scale.rating(rating.rung.key, rating.edge, rating.weakness)
    except (KeyError, ValueError) as exc:
        raise CheckError(f"{rating} isn't a valid {stat.scale.name}: {exc}") from exc


def _difficulty(value, stat: StatDef) -> Rating:
    if isinstance(value, Rating):
        return _on_scale(value, stat)
    try:
        return stat.scale.parse(value)
    except ValueError as exc:
        raise CheckError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def modifier_providers() -> list:
    """The callables named by `settings.RP_RULES_MODIFIER_PROVIDERS`.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If one can't be imported.
    """
    providers = []
    for path in setting("RP_RULES_MODIFIER_PROVIDERS") or ():
        try:
            providers.append(resolve_dotted(path))
        except (ImportError, AttributeError) as exc:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"RP_RULES_MODIFIER_PROVIDERS: can't import {path!r}: {exc}"
            ) from exc
    return providers


def collect_modifiers(check: Check, subjects: dict) -> list[tuple[str, object]]:
    """Every `(owner_side, modifier)` offered for `check`, before any filtering."""
    pairs = [(ACTOR, m) for m in modifiers_of(subjects[ACTOR], check)]
    if subjects.get(TARGET) is not None:
        pairs += [(TARGET, m) for m in modifiers_of(subjects[TARGET], check)]
    loose: list = []
    for provider in modifier_providers():
        loose += list(provider(check) or ())
    loose += list(check.modifiers)
    for modifier in loose:
        side = getattr(modifier, "side", None) or ACTOR
        if side not in SIDES:
            raise ValueError(f"{modifier!r}: side must be one of {list(SIDES)}, got {side!r}")
        pairs.append((side, modifier))
    return pairs


def _call_order(pair) -> tuple:
    owner, modifier = pair
    return (
        getattr(modifier, "priority", 0) or 0,
        owner,
        str(getattr(modifier, "key", "")),
        str(getattr(modifier, "label", "")),
    )


def _active(state: _State) -> list[tuple[str, object]]:
    active = []
    for owner, modifier in collect_modifiers(state.check, state.subjects):
        visibility = getattr(modifier, "visibility", None) or OPEN
        _check_visibility(visibility, modifier)
        if state.mode == ESTIMATE and not visible_to(visibility, owner, state.viewer):
            continue
        if modifier.applies(ResolutionContext(state, modifier, owner)):
            active.append((owner, modifier))
    # Deterministic call order so ON_OUTCOME side effects and notes don't depend
    # on collection order either.
    return sorted(active, key=_call_order)


def _run_phase(state: _State, active, phase: str) -> None:
    state.phase = phase
    staged: list = []
    for owner, modifier in active:
        if phase in modifier.hooks():
            modifier.apply(phase, ResolutionContext(state, modifier, owner, staged))
    state.commit(staged)


def _contest(state: _State) -> Contest:
    actor, actor_bonus = state.effective(ACTOR)
    target, target_bonus = state.effective(TARGET)
    return Contest(actor, target, actor_bonus, target_bonus, opposed=state.check.opposed)


def _frozen(mapping: dict) -> MappingProxyType:
    return MappingProxyType(dict(mapping))


def _breakdown_kwargs(state: _State) -> dict:
    return {
        "check": state.check,
        "ruleset_version": state.ruleset.version,
        "ruleset_digest": state.ruleset.digest,
        "stats": _frozen(state.stats),
        "ratings": _frozen(state.ratings),
        "effective": _frozen({side: state.effective(side)[0] for side in SIDES}),
        "bonuses": _frozen({side: state.effective(side)[1] for side in SIDES}),
        "ledger": tuple(state.ledger),
        "notes": tuple(state.notes),
    }


def default_roller() -> Roller:
    """`settings.RP_RULES_ROLLER` (a dotted path to a zero-argument factory), else `RandomRoller()`."""
    path = setting("RP_RULES_ROLLER")
    if not path:
        return RandomRoller()
    try:
        factory = resolve_dotted(path)
    except (ImportError, AttributeError) as exc:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"RP_RULES_ROLLER: can't import {path!r}: {exc}") from exc
    return factory()


def run_check(
    check: Check, *, roller: Roller | None = None, ruleset: Ruleset | None = None
) -> CheckResult:
    """Resolve `check` through every check phase. See `checks.resolve_check`."""
    state = _State(check, ruleset or get_ruleset(), RESOLVE, STAFF)
    active = _active(state)
    for phase in CHECK_PHASES:
        if phase == ON_OUTCOME:
            state.resolution = state.ruleset.resolver.resolve(
                _contest(state), roller or default_roller()
            )
        _run_phase(state, active, phase)
    return CheckResult(**_breakdown_kwargs(state), resolution=state.resolution)


def run_estimate(check: Check, *, viewer: str, ruleset: Ruleset | None = None) -> CheckEstimate:
    """Estimate `check` for `viewer`. See `checks.estimate_check`."""
    state = _State(check, ruleset or get_ruleset(), ESTIMATE, viewer)
    active = _active(state)
    for phase in CHECK_PHASES:
        if phase == ON_OUTCOME:
            break
        _run_phase(state, active, phase)
    odds = state.ruleset.resolver.estimate(_contest(state))
    return CheckEstimate(**_breakdown_kwargs(state), odds=odds, viewer=viewer)


def applicable_modifiers(
    check: Check, *, ruleset: Ruleset | None = None
) -> list[tuple[str, object]]:
    """`(owner_side, modifier)` for every modifier that would apply to `check`.

    For previews ("Expertise: Performance would apply"); nothing runs.
    """
    state = _State(check, ruleset or get_ruleset(), RESOLVE, STAFF)
    return _active(state)


__all__ = [
    "ESTIMATE",
    "RESOLVE",
    "ResolutionContext",
    "applicable_modifiers",
    "collect_modifiers",
    "default_roller",
    "modifier_providers",
    "run_check",
    "run_estimate",
]
