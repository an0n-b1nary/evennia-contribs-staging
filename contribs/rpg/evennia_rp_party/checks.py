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
            if not 0 <= value <= (1 if name == "RP_PARTY_ENCORE_FACTOR" else 100):
                raise ValueError
        except ValueError:
            errors.append(
                Error(
                    f"{name} must be an exact number within its documented bounds.",
                    id="rp_party.E001",
                )
            )
    return errors
