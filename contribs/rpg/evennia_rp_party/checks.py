# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.core.checks import Error
from evennia_rp_combat.partners import number

from . import conf


def check_configuration(app_configs=None, **kwargs):
    errors = []
    for name in conf.DEFAULTS:
        try:
            value = number(conf.get(name))
            maximum = (
                500
                if name == "RP_PARTY_SURGE_COST"
                else 1
                if name == "RP_PARTY_ENCORE_FACTOR"
                else 100
            )
            if (
                not 0 <= value <= maximum
                or (name == "RP_PARTY_SURGE_COST" and value == 0)
                or (name == "RP_PARTY_STAGGER_POINTS" and value.denominator != 1)
            ):
                raise ValueError
        except ValueError:
            errors.append(
                Error(
                    f"{name} must be an exact number within its documented bounds.",
                    id="rp_party.E001",
                )
            )
    from .boss import presets

    try:
        presets()
    except ValueError as exc:
        errors.append(Error(str(exc), id="rp_party.E002"))
    return errors
