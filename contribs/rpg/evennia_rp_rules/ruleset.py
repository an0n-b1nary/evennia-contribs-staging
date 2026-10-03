# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The ruleset: a game's scales, stats, tags, outcomes and resolver, as data.

A game describes its rules as a plain dict (normally `RULESET` in a module such
as `world/ruleset.py`) and points `RP_RULES_RULESET` at it:

    RULESET = {
        "version": "2026-10",
        "scales": {"grade": {"rungs": [...], "edge": [...], "weakness": [...]}},
        "stats": [{"key": "charisma", "name": "Charisma", "aliases": ["cha"]}],
        "tags": [{"key": "performance", "name": "Performance", "kind": "domain"}],
        "outcomes": [{"key": "failure", "label": "Failure", "degree": -1, "success": False}, ...],
        "resolver": {"path": "evennia_rp_rules.resolvers.GradedResolver", "params": {...}},
    }

`Ruleset.from_spec()` validates the whole thing and reports every problem at
once (see `issues.py` for the ids). The contrib ships no stat names or numbers
of its own beyond the neutral `example_ruleset`, which is the default.

Nothing here imports Django at module level: `get_ruleset()` reads settings
lazily, and everything else is plain Python the odds tool can use without a
configured game.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType

from evennia_rp_rules import _spec
from evennia_rp_rules._config import resolve_dotted as _resolve_dotted
from evennia_rp_rules._config import setting
from evennia_rp_rules.issues import WARNING, Issue, RulesetError
from evennia_rp_rules.outcomes import OutcomeLadder
from evennia_rp_rules.resolvers import Contest, Resolver, ResolverConfigError
from evennia_rp_rules.scales import Rating, Scale, scales_from_spec

DEFAULT_RULESET = "evennia_rp_rules.example_ruleset"
DEFAULT_RESOLVER = "evennia_rp_rules.resolvers.GradedResolver"
DEFAULT_TAG_KIND = "domain"

_TOP_LEVEL = {"version", "scales", "default_scale", "stats", "tags", "outcomes", "resolver"}


@dataclass(frozen=True)
class StatDef:
    """A stat the ruleset defines: key, display name, and the scale it's rated on."""

    key: str
    name: str
    scale: Scale
    aliases: tuple[str, ...] = ()
    description: str = ""
    category: str = ""

    def spellings(self) -> tuple[str, ...]:
        return (self.key, self.name, *self.aliases)


@dataclass(frozen=True)
class TagDef:
    """A tag (a domain such as "Performance", an element such as "Fire").

    Tags have no intrinsic effect; abilities and modifiers refer to them.
    """

    key: str
    name: str
    kind: str = DEFAULT_TAG_KIND
    aliases: tuple[str, ...] = ()
    description: str = ""

    def spellings(self) -> tuple[str, ...]:
        return (self.key, self.name, *self.aliases)


class Ruleset:
    """A validated ruleset. Build one with `Ruleset.from_spec()`."""

    def __init__(
        self,
        *,
        version: str,
        scales: dict[str, Scale],
        default_scale: Scale,
        stats: dict[str, StatDef],
        tags: dict[str, TagDef],
        ladder: OutcomeLadder,
        resolver: Resolver,
        spec: Mapping,
    ):
        self.version = version
        self.scales = scales
        self.default_scale = default_scale
        self.stats = stats
        self.tags = tags
        self.ladder = ladder
        self.resolver = resolver
        self.spec = spec
        self.digest = spec_digest(spec)

    def __repr__(self) -> str:
        return f"<Ruleset {self.version} {self.digest}>"

    # -- construction -------------------------------------------------------

    @classmethod
    def from_spec(cls, spec: Mapping) -> Ruleset:
        """Validate `spec` and build a ruleset.

        Raises:
            RulesetError: Carrying every error-level issue found.
        """
        ruleset, issues = _build(spec)
        errors = [issue for issue in issues if issue.level == "error"]
        if errors or ruleset is None:
            raise RulesetError(errors)
        return ruleset

    @staticmethod
    def validate(spec: Mapping) -> list[Issue]:
        """Every issue in `spec`, without raising."""
        return _build(spec)[1]

    # -- lookup -------------------------------------------------------------

    def find_stat(self, text: str) -> StatDef:
        """Resolve player input to a stat: exact key/name/alias, else a unique prefix.

        Raises:
            LookupError: Player-readable "unknown" or "ambiguous" message.
        """
        return match_spelling(self.stats.values(), text, "stat")

    def find_tag(self, text: str, *, kind: str | None = None) -> TagDef:
        """Resolve player input to a tag, optionally only of one `kind`."""
        tags = [t for t in self.tags.values() if kind is None or t.kind == kind]
        return match_spelling(tags, text, kind or "tag")

    def scale(self, key: str | None = None) -> Scale:
        return self.default_scale if key is None else self.scales[key]

    def parse_rating(self, text: str, *, scale: str | None = None) -> Rating:
        """Parse `"B++"` on the named scale (default scale if omitted)."""
        return self.scale(scale).parse(text)


def match_spelling(candidates, text: str, noun: str):
    """Resolve player input to one of `candidates` (anything with `spellings()` and `name`).

    An exact key, name or alias wins; otherwise a unique prefix of one.

    Raises:
        LookupError: Player-readable "unknown" or "ambiguous" message.
    """
    candidates = list(candidates)
    needle = str(text).strip().casefold()
    if not needle:
        raise LookupError(f"No {noun} given.")
    exact = [c for c in candidates if needle in {s.casefold() for s in c.spellings()}]
    if len(exact) == 1:
        return exact[0]
    prefixed = [
        c for c in candidates if any(s.casefold().startswith(needle) for s in c.spellings())
    ]
    if len(prefixed) == 1:
        return prefixed[0]
    if prefixed:
        names = ", ".join(sorted(c.name for c in prefixed))
        raise LookupError(f"'{text}' could mean {names}.")
    names = ", ".join(sorted(c.name for c in candidates))
    raise LookupError(f"Unknown {noun} '{text}'. Choose from: {names}.")


def spec_digest(spec: Mapping) -> str:
    """Short stable hash of a spec, recorded with every check for auditability."""
    canonical = json.dumps(spec, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _build(spec) -> tuple[Ruleset | None, list[Issue]]:
    issues: list[Issue] = []
    if _spec.require_mapping(spec, issues, "ruleset") is None:
        return None, issues
    for key in sorted(set(spec) - _TOP_LEVEL, key=str):
        _spec.malformed(
            issues,
            "ruleset",
            f"unknown top-level key {key!r}",
            f"expected one of {sorted(_TOP_LEVEL)}",
        )
    for key in ("version", "scales", "stats", "outcomes"):
        if key not in spec:
            _spec.malformed(issues, "ruleset", f"missing {key!r}")

    version = spec.get("version")
    if "version" in spec and (
        not isinstance(version, str | int)
        or isinstance(version, bool)
        or str(version).strip() == ""
    ):
        _spec.malformed(issues, "version", f"expected a string or integer, got {version!r}")

    scales = scales_from_spec(spec.get("scales", {}), issues) if "scales" in spec else {}
    for scale in scales.values():
        issues.extend(scale.crossings())
    default_scale = _default_scale(spec, scales, issues)
    stats = (
        _stats_from_spec(spec.get("stats"), scales, default_scale, issues)
        if "stats" in spec
        else {}
    )
    tags = _tags_from_spec(spec.get("tags", []), issues)
    ladder = OutcomeLadder.from_spec(spec["outcomes"], issues) if "outcomes" in spec else None
    resolver = (
        _resolver_from_spec(spec.get("resolver", {}), ladder, issues)
        if ladder is not None
        else None
    )

    if any(issue.level == "error" for issue in issues) or default_scale is None or resolver is None:
        return None, issues
    issues.extend(dead_pip_warnings(scales.values(), resolver))
    ruleset = Ruleset(
        version=str(version),
        scales=scales,
        default_scale=default_scale,
        stats=stats,
        tags=tags,
        ladder=ladder,
        resolver=resolver,
        spec=spec,
    )
    return ruleset, issues


def dead_pip_warnings(scales, resolver: Resolver) -> list[Issue]:
    """W001 for each pip that changes no odds against any rung.

    Integer dice and integer band thresholds only "see" whole points, so a pip
    worth a fraction of a point (easy to reach with depreciating curves and
    rung factors) can land in the same bucket as the pip before it and do
    nothing at all. Not an error, since a game may accept it, but almost
    always a tuning slip worth hearing about.
    """
    issues = []
    for scale in scales:
        targets = [scale.rating(rung) for rung in scale.rungs]
        for rung in scale.rungs:
            dead = []
            previous = None
            for net in range(-scale.max_weakness, scale.max_edge + 1):
                rating = scale.rating(rung, edge=max(net, 0), weakness=max(-net, 0))
                odds = [dict(resolver.estimate(Contest(rating, target))) for target in targets]
                if previous is not None and odds == previous[1]:
                    dead.append(
                        f"{rating.display(compact=True)} = {previous[0].display(compact=True)}"
                    )
                previous = (rating, odds)
            if dead:
                issues.append(
                    Issue(
                        "W001",
                        f"scales.{scale.key}: on {rung.label}, these ratings play identically "
                        f"against every rung: {', '.join(dead)}",
                        "the noise only resolves whole points; make those pips worth at least "
                        "a point after rung factors, or widen the score scale",
                        level=WARNING,
                    )
                )
    return issues


def _default_scale(spec, scales: dict[str, Scale], issues: list[Issue]) -> Scale | None:
    key = spec.get("default_scale")
    if key is not None:
        if key not in scales:
            _spec.inconsistent(issues, "default_scale", f"unknown scale {key!r}")
            return None
        return scales[key]
    if len(scales) == 1:
        return next(iter(scales.values()))
    if len(scales) > 1:
        _spec.malformed(issues, "default_scale", "required when more than one scale is defined")
    return None


def _stats_from_spec(raw, scales, default_scale, issues: list[Issue]) -> dict[str, StatDef]:
    items = _spec.require_list(raw, issues, "stats")
    stats: dict[str, StatDef] = {}
    spellings: dict[str, str] = {}
    for index, item in enumerate(items or []):
        where = f"stats[{index}]"
        item = _spec.require_mapping(item, issues, where)
        if item is None:
            continue
        before = len(issues)
        key = _spec.require_key(item.get("key"), issues, f"{where}.key")
        name = _spec.require_text(item.get("name"), issues, f"{where}.name")
        aliases = _spec.text_aliases(item.get("aliases"), issues, f"{where}.aliases")
        scale_key = item.get("scale")
        scale = default_scale
        if scale_key is not None:
            scale = scales.get(scale_key)
            if scale is None:
                _spec.inconsistent(issues, f"{where}.scale", f"unknown scale {scale_key!r}")
        elif scale is None and scales:
            _spec.malformed(issues, f"{where}.scale", "name a scale (no default_scale is set)")
        description = item.get("description", "")
        category = item.get("category", "")
        for field_name, value in (("description", description), ("category", category)):
            if not isinstance(value, str):
                _spec.malformed(issues, f"{where}.{field_name}", f"expected text, got {value!r}")
        if len(issues) > before or scale is None:
            continue
        if key in stats:
            _spec.malformed(issues, f"{where}.key", f"duplicate stat {key!r}")
            continue
        stat = StatDef(key, name, scale, aliases, description, category)
        _claim_spellings(stat, spellings, issues, where, "stat")
        stats[key] = stat
    return stats


def _tags_from_spec(raw, issues: list[Issue]) -> dict[str, TagDef]:
    items = _spec.require_list(raw, issues, "tags", allow_empty=True)
    tags: dict[str, TagDef] = {}
    spellings: dict[str, str] = {}
    for index, item in enumerate(items or []):
        where = f"tags[{index}]"
        item = _spec.require_mapping(item, issues, where)
        if item is None:
            continue
        before = len(issues)
        key = _spec.require_key(item.get("key"), issues, f"{where}.key")
        name = _spec.require_text(item.get("name"), issues, f"{where}.name")
        kind = _spec.require_key(item.get("kind", DEFAULT_TAG_KIND), issues, f"{where}.kind")
        aliases = _spec.text_aliases(item.get("aliases"), issues, f"{where}.aliases")
        description = item.get("description", "")
        if not isinstance(description, str):
            _spec.malformed(issues, f"{where}.description", f"expected text, got {description!r}")
        if len(issues) > before:
            continue
        if key in tags:
            _spec.malformed(issues, f"{where}.key", f"duplicate tag {key!r}")
            continue
        tag = TagDef(key, name, kind, aliases, description)
        # Spellings must be unique within a kind; a domain and an element may share a name.
        _claim_spellings(tag, spellings, issues, where, "tag", namespace=kind)
        tags[key] = tag
    return tags


def _claim_spellings(item, claimed: dict[str, str], issues, where, noun, namespace=""):
    for spelling in {s.casefold() for s in item.spellings()}:
        slot = f"{namespace}:{spelling}"
        owner = claimed.get(slot)
        if owner is not None and owner != item.key:
            _spec.malformed(
                issues, where, f"{noun} spelling {spelling!r} is already used by {owner!r}"
            )
        claimed[slot] = item.key


def _resolver_from_spec(raw, ladder: OutcomeLadder, issues: list[Issue]) -> Resolver | None:
    raw = _spec.require_mapping(raw, issues, "resolver")
    if raw is None:
        return None
    extra = set(raw) - {"path", "params"}
    if extra:
        _spec.malformed(
            issues, "resolver", f"unknown keys {sorted(extra)}", "expected 'path' and 'params'"
        )
    path = raw.get("path", DEFAULT_RESOLVER)
    try:
        cls = _resolve_dotted(path)
    except (ImportError, AttributeError, ValueError) as exc:
        _spec.inconsistent(issues, "resolver.path", f"can't import {path!r}: {exc}")
        return None
    if not hasattr(cls, "from_params"):
        _spec.inconsistent(
            issues, "resolver.path", f"{path!r} has no from_params(ladder, params) classmethod"
        )
        return None
    try:
        return cls.from_params(ladder, raw.get("params", {}))
    except ResolverConfigError as exc:
        for message in exc.messages:
            _spec.inconsistent(issues, "resolver.params", message)
    return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_ruleset_spec(ref) -> Mapping:
    """Find a ruleset spec from a dict, a module path, an attribute path, or a file.

    Accepts:
        - a mapping (returned as is);
        - `"world.ruleset"`: a module, whose `RULESET` attribute is used;
        - `"world.ruleset.MY_RULES"`: an attribute of a module;
        - `"path/to/ruleset.py"`: a file, whose `RULESET` attribute is used.

    Raises:
        RulesetError: If nothing usable is found there (E001).
    """
    if isinstance(ref, Mapping):
        return ref
    if not isinstance(ref, str) or not ref.strip():
        raise RulesetError(
            [Issue("E001", f"ruleset reference must be a dict or a dotted path, got {ref!r}")]
        )
    ref = ref.strip()
    try:
        if ref.endswith(".py"):
            obj = getattr(_load_file(pathlib.Path(ref)), "RULESET", None)
        else:
            try:
                module = import_module(ref)
            except ImportError:
                module = None
            obj = getattr(module, "RULESET", None) if module is not None else _resolve_dotted(ref)
    except (ImportError, AttributeError, OSError) as exc:
        raise RulesetError([Issue("E001", f"can't load ruleset {ref!r}: {exc}")]) from exc
    if not isinstance(obj, Mapping):
        raise RulesetError(
            [Issue("E001", f"ruleset {ref!r} is not a dict (a module needs a RULESET attribute)")]
        )
    return obj


def _load_file(path: pathlib.Path) -> ModuleType:
    if not path.is_file():
        raise OSError(f"no such file: {path}")
    module_spec = importlib.util.spec_from_file_location(f"_rp_ruleset_{path.stem}", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


_CACHE: dict[str, Ruleset] = {}


def get_ruleset() -> Ruleset:
    """The game's ruleset, from `settings.RP_RULES_RULESET` (cached).

    Defaults to the neutral `evennia_rp_rules.example_ruleset`. The cache is
    cleared whenever an `RP_RULES_*` setting changes (tests use
    `override_settings`) and by `reset_ruleset_cache()`.

    Raises:
        RulesetError: If the configured ruleset is invalid. The app's system
            check reports the same issues at startup.
    """
    ruleset = _CACHE.get("ruleset")
    if ruleset is None:
        ref = setting("RP_RULES_RULESET", DEFAULT_RULESET)
        ruleset = Ruleset.from_spec(load_ruleset_spec(ref))
        _CACHE["ruleset"] = ruleset
    return ruleset


def reset_ruleset_cache(**kwargs) -> None:
    """Forget the cached ruleset. Doubles as a `setting_changed` receiver."""
    setting = kwargs.get("setting")
    if setting is None or str(setting).startswith("RP_RULES_"):
        _CACHE.clear()


__all__ = [
    "Ruleset",
    "RulesetError",
    "StatDef",
    "TagDef",
    "get_ruleset",
    "load_ruleset_spec",
    "match_spelling",
    "reset_ruleset_cache",
    "spec_digest",
]
