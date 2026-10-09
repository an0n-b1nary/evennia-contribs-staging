# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Runtime controls and host policy hooks."""

from django.conf import settings

from evennia_links.collect import resolve_dotted
from evennia_links.runtime import register


def nonnegative(value):
    return type(value) is int and value >= 0


def positive(value):
    return type(value) is int and value > 0


def fraction(value):
    return type(value) in (int, float) and 0 <= value < 1


def boolean(value):
    return type(value) is bool


def register_controls():
    for name, default, validator in (
        ("RP_RESOURCES_REVEALED", True, boolean),
        ("RP_RESOURCES_WEEKLY_QUANTITY", 6, nonnegative),
        ("RP_RESOURCES_BASE_CAP", 30, positive),
        ("RP_RESOURCES_TAPER_FRACTION", 0.8, fraction),
        ("RP_RESOURCES_PERIOD_SECONDS", 604800, positive),
        ("RP_RESOURCES_LEAN_MULTIPLIER", 2, positive),
    ):
        register(name, default, validator=validator)


def hook(name):
    value = getattr(settings, name, None)
    return resolve_dotted(value) if isinstance(value, str) else value


def categories():
    return dict(
        getattr(
            settings,
            "RP_RESOURCES_CATEGORIES",
            [("materials", "Materials"), ("provisions", "Provisions"), ("essences", "Essences")],
        )
    )


def is_staff(character):
    return bool(
        character.locks.check_lockstring(
            character, getattr(settings, "RP_RESOURCES_STAFF_LOCK", "cmd:perm(Builder)")
        )
    )


def visible(character):
    from evennia_links.runtime import get

    return get("RP_RESOURCES_REVEALED") or is_staff(character)
