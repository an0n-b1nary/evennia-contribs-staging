# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django system checks for evennia_rp_chargen.

evennia_rp_chargen.E001  RP_CHARGEN_ALLOCATION can't be built, or doesn't fit the ruleset
evennia_rp_chargen.E002  a pip budget or cap isn't a whole number of at least 0
"""

from __future__ import annotations

from django.core import checks
from django.core.exceptions import ImproperlyConfigured

from evennia_rp_chargen import conf
from evennia_rp_chargen.allocation import get_allocation
from evennia_rp_rules.issues import RulesetError
from evennia_rp_rules.ruleset import get_ruleset

APP = "evennia_rp_chargen"


def check_allocation(app_configs=None, **kwargs) -> list:
    try:
        allocation = get_allocation()
    except ImproperlyConfigured as exc:
        return [checks.Error(str(exc), id=f"{APP}.E001")]
    try:
        ruleset = get_ruleset()
    except RulesetError:
        return []  # evennia_rp_rules reports the ruleset itself
    return [
        checks.Error(f"RP_CHARGEN_ALLOCATION: {problem}", id=f"{APP}.E001")
        for problem in allocation.config_problems(ruleset)
    ]


def check_pip_settings(app_configs=None, **kwargs) -> list:
    errors = []
    for name in ("RP_CHARGEN_PIP_BUDGET", "RP_CHARGEN_PIP_CAP", "RP_CHARGEN_WEAKNESS_CAP"):
        value = conf.get(name)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            errors.append(
                checks.Error(
                    f"{name} must be None or a whole number of at least 0, got {value!r}",
                    id=f"{APP}.E002",
                )
            )
    return errors
