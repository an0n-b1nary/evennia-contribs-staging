# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Provisional, host-configurable Party calibration values."""

from evennia_rp_rules._config import setting

DEFAULTS = {
    "RP_PARTY_SPIRIT_COEFFICIENT": "1",
    "RP_PARTY_SUPPORT_POINTS": "5",
    "RP_PARTY_BOOST_CAP": "30",
    "RP_PARTY_PINPOINT_PENALTY": "10",
    "RP_PARTY_ENCORE_FACTOR": "1/2",
}


def get(name):
    return setting(name, DEFAULTS[name])


def boolean(value):
    return type(value) is bool


def register_runtime():
    from evennia_links.runtime import register

    for name, description in (
        ("RP_PARTY_REVEALED", "Expose fight-local Party commands and tactics."),
        ("RP_PARTY_FROZEN", "Freeze new Party coordination; inspection, chat and cleanup remain."),
    ):
        register(name, False, validator=boolean, description=description)
