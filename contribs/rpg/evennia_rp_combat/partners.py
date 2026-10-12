# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pure partner contracts, called inside the coordinator's transaction.

Providers are trusted host code, not player policies. Inputs are detached
JSON state; providers must not query models, random generators or presence.
Only validated numeric outputs reach reaction policies. A provider owns
only its versioned section under ``state['partners']``.
"""

import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from fractions import Fraction
from functools import wraps

from django.apps import apps
from django.utils.module_loading import import_string

from . import conf
from .data import REACTIONS, CombatError


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, str, Fraction)):
        raise CombatError("Partner modifiers must be exact finite numbers.")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise CombatError("Partner modifiers must be exact finite numbers.") from exc


def atomic_requests(operation):
    """A refused explicit spend leaves even a pure engine caller unchanged."""

    @wraps(operation)
    def apply(state, *args, **kwargs):
        if kwargs.get("partner_requests") is None or kwargs["partner_requests"] == {}:
            return operation(state, *args, **kwargs)
        candidate = deepcopy(state)
        result = operation(candidate, *args, **kwargs)
        state.clear()
        state.update(candidate)
        return result

    return apply


@dataclass(frozen=True)
class Declaration:
    """Public packet identity, with no draw, RPS bet or reaction commitment."""

    actor_id: str
    target_id: str
    action: str
    effects: tuple[str, ...]
    domain_effect: str
    exchange_id: str
    hit: int
    domain: str = ""


@dataclass(frozen=True)
class SupportSpread:
    """Ordinary Spirit only; primary healing/riders and action costs stay single."""

    recipients: tuple[str, ...]
    factor: str = "1"

    def __post_init__(self):
        if (
            not isinstance(self.recipients, tuple)
            or any(not isinstance(ident, str) for ident in self.recipients)
            or len(set(self.recipients)) != len(self.recipients)
        ):
            raise CombatError("Support recipients must be distinct saved participant identifiers.")
        factor = number(self.factor)
        if not 0 <= factor <= 1:
            raise CombatError("Support spread strength must be between 0 and 1.")
        object.__setattr__(self, "factor", str(factor))


@dataclass(frozen=True)
class PacketModifiers:
    """Percentage points; Formation raises the defender's reaction chance.

    Damage boost and Surge are additive for damage. Surge alone also
    modifies ordinary support output; neither applies to counterdamage.
    Facts are public string pairs retained for explaining the snapshot.
    """

    formation_penalty: str = "0"
    damage_boost: str = "0"
    surge: str = "0"
    reaction_penalty: str = "0"
    cover_eligible: bool = False
    auto_resolve: bool = True
    facts: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        for name in ("formation_penalty", "damage_boost", "surge", "reaction_penalty"):
            value = number(getattr(self, name))
            if not 0 <= value <= 100:
                raise CombatError("Partner modifier percentage points must be between 0 and 100.")
            object.__setattr__(self, name, str(value))
        if type(self.cover_eligible) is not bool or type(self.auto_resolve) is not bool:
            raise CombatError("Partner permission modifiers must be booleans.")
        if (
            not isinstance(self.facts, tuple)
            or len(self.facts) > 32
            or any(
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(not isinstance(value, str) or len(value) > 200 for value in pair)
                for pair in self.facts
            )
        ):
            raise CombatError("Partner snapshot facts must be bounded public text pairs.")

    def frozen(self):
        value = asdict(self)
        value["facts"] = [list(pair) for pair in self.facts]
        return value

    @classmethod
    def thaw(cls, value):
        try:
            if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
                raise ValueError
            return cls(**{**value, "facts": tuple(tuple(pair) for pair in value["facts"])})
        except (TypeError, ValueError) as exc:
            raise CombatError("Invalid saved partner packet modifiers.") from exc


@dataclass(frozen=True)
class Event:
    """A committed engine boundary; callback returns only its own section.

    ``packet`` follows actual damage/support, ``exchange_end`` follows the
    personal clock, and ``cancel`` identifies an unexecuted target packet.
    Never use an accepted reaction as an action/reward event.
    """

    kind: str
    actor_id: str
    exchange_id: str
    hit: int
    target_id: str = ""
    damage: int = 0
    counter_damage: int = 0
    healing: int = 0
    spirit: int = 0
    potential_spirit: int = 0
    empowered: bool = False
    actor_was_participating: bool = False
    target_was_participating: bool = False


@dataclass(frozen=True)
class Transition:
    """An owned state envelope and public notices, committed together."""

    section: dict
    notices: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.notices, tuple) or any(
            not isinstance(line, str) or len(line) > 400 or "\n" in line for line in self.notices
        ):
            raise CombatError("Partner notices must be bounded public text lines.")


@dataclass(frozen=True)
class Provider:
    snapshot: Callable
    upgrade: Callable
    transition: Callable | None = None
    status: Callable | None = None
    help: Callable | None = None
    support: Callable | None = None
    reserve: Callable | None = None

    def __post_init__(self):
        if (
            not callable(self.snapshot)
            or not callable(self.upgrade)
            or any(
                callback is not None and not callable(callback)
                for callback in (
                    self.transition,
                    self.status,
                    self.help,
                    self.support,
                    self.reserve,
                )
            )
        ):
            raise CombatError("Combat partner providers need callable contracts.")


def registered():
    """Import only providers whose declared app is actually installed."""
    registry = conf.get("RP_COMBAT_PARTNERS")
    if not isinstance(registry, dict):
        raise CombatError("RP_COMBAT_PARTNERS must be a mapping.")
    result = {}
    for key, entry in registry.items():
        if (
            not isinstance(key, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) is None
            or not isinstance(entry, dict)
            or set(entry) != {"app", "provider"}
            or any(not isinstance(v, str) or not v for v in entry.values())
        ):
            raise CombatError("Each combat partner needs a stable key, app and provider path.")
        if not apps.is_installed(entry["app"]):
            continue
        try:
            provider = import_string(entry["provider"])
        except (ImportError, AttributeError) as exc:
            raise CombatError(f"Cannot import combat partner {key}.") from exc
        if not isinstance(provider, Provider):
            raise CombatError(f"Combat partner {key} must export a Provider.")
        result[key] = provider
    return result


def envelope(section):
    if (
        not isinstance(section, dict)
        or set(section) != {"schema", "data"}
        or type(section["schema"]) is not int
        or section["schema"] < 1
        or not isinstance(section["data"], dict)
    ):
        raise CombatError("Partner state needs a positive schema and a data mapping.")
    try:
        json.dumps(section, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CombatError("Partner state must contain finite JSON data.") from exc
    return deepcopy(section)


def upgrade_sections(state):
    sections = state.get("partners")
    if not isinstance(sections, dict):
        raise CombatError("Combat partner state must be a mapping.")
    for key, section in sections.items():
        if not isinstance(key, str):
            raise CombatError("Combat partner state keys must be text.")
        envelope(section)
    for key, provider in registered().items():
        sections[key] = envelope(provider.upgrade(deepcopy(sections.get(key))))
    return state


def declaration(exchange, target_id):
    return Declaration(
        exchange["actor"],
        str(target_id),
        exchange["move"]["action"],
        tuple(exchange["move"]["effects"]),
        exchange["domain_effect"],
        exchange["id"],
        exchange["hit"],
        exchange["domain"],
    )


def snapshot(state, exchange):
    """Freeze once per declared hit, before any target accepts a reaction."""
    snapshots = {}
    for target_id in exchange["targets"]:
        values = {}
        for key, provider in registered().items():
            value = provider.snapshot(deepcopy(state), declaration(exchange, target_id))
            if not isinstance(value, PacketModifiers):
                raise CombatError(f"Combat partner {key} returned invalid packet modifiers.")
            values[key] = value.frozen()
        snapshots[target_id] = values
    exchange["partner_modifiers"] = snapshots


def install(state, key, result):
    """Providers can replace only their own section and append public notices."""
    section = result.section if isinstance(result, Transition) else result
    state["partners"][key] = envelope(section)
    if isinstance(result, Transition) and result.notices:
        state.setdefault("notices", []).extend(result.notices)


def reserve(state, exchange, requests=None):
    """Explicit host requests, before frozen modifiers or automatic execution.

    Each request names one declared target. Auto-Act passes no requests.
    The owning provider validates its remaining JSON options and resource
    rules. Failure rolls back with the declaration in the coordinator.
    """
    requests = {} if requests is None else requests
    if not isinstance(requests, dict):
        raise CombatError("Partner declaration requests must be a mapping.")
    present = registered()
    for key, request in requests.items():
        provider = present.get(key)
        if provider is None or provider.reserve is None:
            raise CombatError("That partner's declaration spending is unavailable.")
        if (
            isinstance(request, dict)
            and request.get("target") == ""
            and len(exchange["targets"]) == 1
        ):
            request = {**request, "target": exchange["targets"][0]}
        if not isinstance(request, dict) or request.get("target") not in exchange["targets"]:
            raise CombatError("A partner spend must name one declared target.")
        try:
            json.dumps(request, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CombatError("Partner declaration requests must be finite JSON data.") from exc
        install(
            state,
            key,
            provider.reserve(
                deepcopy(state), declaration(exchange, request["target"]), deepcopy(request)
            ),
        )


def modifiers(exchange, target_id):
    """Use frozen values only; removing a provider disables its modifiers."""
    values = exchange.get("partner_modifiers", {}).get(str(target_id), {})
    present = registered()
    numbers = {
        key: Fraction(0)
        for key in ("formation_penalty", "damage_boost", "surge", "reaction_penalty")
    }
    cover, automatic, facts = False, True, []
    for key, data in values.items():
        if key not in present:
            continue
        value = PacketModifiers.thaw(data)
        for field in numbers:
            numbers[field] += number(getattr(value, field))
        cover |= value.cover_eligible
        automatic &= value.auto_resolve
        facts.extend(value.facts)
    return PacketModifiers(
        **{key: str(min(100, value)) for key, value in numbers.items()},
        cover_eligible=cover,
        auto_resolve=automatic,
        facts=tuple(facts[:32]),
    )


def support_spread(state, exchange, target_id):
    result = None
    for key, provider in registered().items():
        if provider.support is None:
            continue
        value = provider.support(deepcopy(state), declaration(exchange, target_id))
        if value is None:
            continue
        if not isinstance(value, SupportSpread) or result is not None:
            raise CombatError(
                f"Combat partner {key} returned conflicting or invalid support spread."
            )
        result = value
    return result


def emit(state, event):
    for key, provider in registered().items():
        if provider.transition is not None:
            install(state, key, provider.transition(deepcopy(state), event))


def lines(state, subject_id, *, help=False):
    result = []
    present = registered()
    for key in sorted(state["partners"].keys() - present.keys()):
        result.append(f"{key}: partner rules unavailable; retained data is preserved.")
    for provider in present.values():
        callback = provider.help if help else provider.status
        if callback is None:
            continue
        values = callback(deepcopy(state), str(subject_id))
        if not isinstance(values, tuple) or any(
            not isinstance(value, str) or len(value) > 500 or "\n" in value for value in values
        ):
            raise CombatError("Combat partner display hooks must return bounded text lines.")
        result.extend(values)
    return result


def reactions(exchange, target_id):
    return (
        ("resist", "overpower")
        if str(target_id) in exchange.get("covered_targets", ())
        else REACTIONS
    )
