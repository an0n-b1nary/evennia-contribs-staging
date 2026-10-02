# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django system checks: surface ruleset and settings problems at startup.

    evennia_rp_rules.E001  the ruleset is malformed, or can't be loaded at all
    evennia_rp_rules.E002  the ruleset is inconsistent (unknown references, bad resolver params)
    evennia_rp_rules.E003  pips can cross a rung
    evennia_rp_rules.W001  a pip changes no odds
    evennia_rp_rules.W002  an RP_RULES_* dotted path can't be imported, or isn't the right shape

E-level issues stop the server and `migrate`, which is the point: a rules
table that lets `B +++++` reach `A` should never go live. W002 is a warning
because the path may belong to an optional partner; every check that needs it
will fail loudly at runtime until it's fixed.
"""

from __future__ import annotations

from django.core import checks

from evennia_rp_rules._config import resolve_dotted, setting
from evennia_rp_rules.issues import WARNING, RulesetError
from evennia_rp_rules.ruleset import DEFAULT_RULESET, Ruleset, load_ruleset_spec

APP = "evennia_rp_rules"


def _message(issue):
    cls = checks.Warning if issue.level == WARNING else checks.Error
    return cls(issue.message, hint=issue.hint, id=f"{APP}.{issue.id}")


def check_ruleset(app_configs=None, **kwargs) -> list:
    """Validate `RP_RULES_RULESET` and report every issue."""
    ref = setting("RP_RULES_RULESET", DEFAULT_RULESET)
    try:
        spec = load_ruleset_spec(ref)
    except RulesetError as exc:
        return [_message(issue) for issue in exc.issues]
    return [_message(issue) for issue in Ruleset.validate(spec)]


def _path_problem(name: str, path, *, needs: str | None = None) -> checks.Warning | None:
    try:
        obj = resolve_dotted(path)
    except (ImportError, AttributeError) as exc:
        return checks.Warning(
            f"{name}: can't import {path!r}: {exc}",
            hint="fix the dotted path, or remove the setting if the partner isn't installed",
            id=f"{APP}.W002",
        )
    if needs and not callable(getattr(obj, needs, None)):
        return checks.Warning(f"{name}: {path!r} has no {needs}()", id=f"{APP}.W002")
    if not needs and not callable(obj):
        return checks.Warning(f"{name}: {path!r} isn't callable", id=f"{APP}.W002")
    return None


def check_dotted_paths(app_configs=None, **kwargs) -> list:
    """W002 for every RP_RULES_* path setting that won't resolve."""
    found: list[tuple[str, object, str | None]] = []
    for name in ("RP_RULES_SUBJECT_ADAPTER", "RP_RULES_VOCABULARY", "RP_RULES_ROLLER"):
        path = setting(name)
        if path:
            found.append((name, path, None))
    providers = setting("RP_RULES_MODIFIER_PROVIDERS") or ()
    if isinstance(providers, str):
        return [
            checks.Warning(
                "RP_RULES_MODIFIER_PROVIDERS must be a list of dotted paths, not one string",
                id=f"{APP}.W002",
            )
        ]
    for index, path in enumerate(providers):
        found.append((f"RP_RULES_MODIFIER_PROVIDERS[{index}]", path, None))
    kinds = setting("RP_RULES_EFFECT_KINDS") or {}
    if not isinstance(kinds, dict):
        return [
            checks.Warning(
                "RP_RULES_EFFECT_KINDS must be a dict of {kind: dotted path}", id=f"{APP}.W002"
            )
        ]
    for kind, path in kinds.items():
        found.append((f"RP_RULES_EFFECT_KINDS[{kind!r}]", path, "from_spec"))
    return [
        problem
        for name, path, needs in found
        if (problem := _path_problem(name, path, needs=needs)) is not None
    ]


__all__ = ["check_dotted_paths", "check_ruleset"]
