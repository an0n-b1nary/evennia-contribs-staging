# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Immutable, JSON-compatible fight inputs with explicit capability boundaries."""

from dataclasses import asdict, dataclass
from fractions import Fraction

REACTIONS = ("evade", "resist", "overpower")
ACTIONS = ("attack", "spell", "assist", "dispirit")
TIERS = {
    "light": (-2, 2),
    "quick": (-1, 1),
    "balanced": (0, 0),
    "strong": (1, -1),
    "heavy": (2, -2),
}
EFFECTS = {
    "heal": ("assist",),
    **{
        e: ("attack", "spell")
        for e in ("long_range", "evade_stance", "resist_stance", "overpower_stance", "strain")
    },
}


class CombatError(ValueError):
    """A safe player-facing refusal; no state has been spent."""


@dataclass(frozen=True)
class Move:
    key: str = "balanced"
    name: str = "Balanced"
    action: str = "attack"
    power: int = 0
    accuracy: int = 0
    kind: str = "standard"
    wording: str = ""
    element: str = ""
    effects: tuple[str, ...] = ()
    domain: str = ""
    domain_mode: str = "waive"
    assist_stat: str = ""
    revision: int = 1

    def __post_init__(self):
        for field, limit in (
            ("key", 64),
            ("name", 80),
            ("wording", 240),
            ("element", 64),
            ("domain", 64),
            ("assist_stat", 64),
        ):
            text = getattr(self, field)
            if not isinstance(text, str) or len(text) > limit:
                raise CombatError(f"{field} must be text of at most {limit} characters.")
        if self.action not in ACTIONS or self.kind not in ("standard", "improvised", "signature"):
            raise CombatError("Unknown action or move kind.")
        if type(self.power) is not int or type(self.accuracy) is not int:
            raise CombatError("Power and Accuracy must be whole tiers.")
        if self.action in ("attack", "spell"):
            budget = {"standard": 0, "improvised": 1, "signature": 2}[self.kind]
            if (
                self.power + self.accuracy != budget
                or min(self.power, self.accuracy) < -2
                or max(self.power, self.accuracy) > budget + 2
            ):
                raise CombatError("The move's authored tiers exceed its budget.")
        elif self.power or self.accuracy or self.element:
            raise CombatError("Support moves do not use attack tiers or elements.")
        if not isinstance(self.effects, tuple) or any(not isinstance(e, str) for e in self.effects):
            raise CombatError("Effects must be an immutable list of supported names.")
        if len(set(self.effects)) != len(self.effects) or len(self.effects) > (
            2 if self.kind == "signature" else 1 if self.kind == "improvised" else 0
        ):
            raise CombatError("The move exceeds its distinct Effect slots.")
        for effect in self.effects:
            if effect not in EFFECTS or self.action not in EFFECTS[effect]:
                raise CombatError(f"{effect} cannot be used with {self.action}.")
        if self.domain and (self.kind != "signature" or self.domain_mode != "waive"):
            raise CombatError("Only a Signature may build in a domain surcharge waiver.")

    @property
    def cost(self):
        return 0 if self.kind == "standard" else 1 + len(self.effects)

    @property
    def effective_accuracy(self):
        return self.accuracy - sum(e.endswith("_stance") for e in self.effects)

    def as_dict(self):
        data = asdict(self)
        data["effects"] = list(self.effects)
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "effects": tuple(data.get("effects", ()))})


@dataclass(frozen=True)
class Build:
    """Frozen numeric inputs and authored moves; never a live sheet/model."""

    scores: tuple[tuple[str, str], ...]
    moves: tuple[Move, ...] = ()
    effects: tuple[tuple[str, str], ...] = ()
    abilities: tuple[tuple[str, str, int], ...] = ()
    flaws: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        roles = {
            "attack",
            "attack_defense",
            "spell",
            "spell_defense",
            "dispirit",
            "will",
            "agility",
        }
        try:
            if (
                not isinstance(self.scores, tuple)
                or len(self.scores) != 7
                or set(dict(self.scores)) != roles
            ):
                raise ValueError
            for _key, value in self.scores:
                Fraction(value)
            if not isinstance(self.moves, tuple) or any(
                not isinstance(m, Move) for m in self.moves
            ):
                raise ValueError
            for collection in (self.effects, self.abilities, self.flaws):
                if not isinstance(collection, tuple) or any(
                    not isinstance(row, tuple) for row in collection
                ):
                    raise ValueError
        except (TypeError, ValueError, ZeroDivisionError):
            raise CombatError(
                "A combat Build needs immutable entries and seven finite role scores."
            ) from None

    def score(self, role):
        try:
            from .modifiers import bonus

            return Fraction(dict(self.scores)[role]) + bonus(self, "build", role)
        except KeyError:
            raise CombatError(f"The build lacks its {role} stat.") from None

    def as_dict(self):
        return {
            "scores": dict(self.scores),
            "moves": [m.as_dict() for m in self.moves],
            "effects": [list(e) for e in self.effects],
            "abilities": [list(a) for a in self.abilities],
            "flaws": [list(f) for f in self.flaws],
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            tuple(data["scores"].items()),
            tuple(Move.from_dict(m) for m in data.get("moves", ())),
            tuple(tuple(e) for e in data.get("effects", ())),
            tuple(tuple(a) for a in data.get("abilities", ())),
            tuple(tuple(f) for f in data.get("flaws", ())),
        )


@dataclass(frozen=True)
class ReactionView:
    """Public incoming facts. No RPS, committed draw, target model or sheet."""

    action: str
    power: int
    accuracy: int
    spirit: int
    # Explicit own information, safe for a defender's policy.
    build: Build
    hp: int = 100
    reserves: int = 3
    transcendence: int = 0
    spirit_self: int = 0
    pressure: int = 0
    penalties: tuple[tuple[str, str], ...] = ()
    bonuses: tuple[tuple[str, str], ...] = ()
    estimates: bool = True


@dataclass(frozen=True)
class ActionView:
    """An actor policy gets its own build and eligible public targets only."""

    build: Build
    targets: tuple[tuple[int, int | None], ...]  # id, public Vitality or None
    reserves: int = 3
    allies: tuple[tuple[int, int | None], ...] = ()
    provoker: int | None = None
    hp: int = 100
