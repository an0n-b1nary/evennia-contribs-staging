# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.conf import settings

from evennia_links.collect import resolve_dotted
from evennia_links.runtime import get, register

FEE_KINDS = (
    "stall_claim",
    "stall_upkeep",
    "listing",
    "sale",
    "trade",
    "shop_approval",
    "shop_upkeep",
    "craft",
)


def nonnegative(value):
    return type(value) is int and value >= 0


def positive(value):
    return type(value) is int and value > 0


def boolean(value):
    return type(value) is bool


def fraction(value):
    return type(value) in (int, float) and 0 <= value < 1


def weeks(value):
    return type(value) in (int, float) and 0 < value <= 10000


def register_controls():
    for name, default, validator in (
        ("REVEALED", True, boolean),
        ("FROZEN", False, boolean),
        ("WEEKLY_AMOUNT", 100, nonnegative),
        ("BASE_CAP_WEEKS", 5, weeks),
        ("TAPER_FRACTION", 0.8, fraction),
        ("PERIOD_SECONDS", 604800, positive),
        ("STARTING_STIPEND", 100, nonnegative),
        ("REVEAL_STIPEND", 100, nonnegative),
        ("OFFER_TIMEOUT", 600, positive),
        ("MAX_OPEN_OFFERS", 5, positive),
    ):
        register(f"RP_ECONOMY_{name}", default, validator=validator)
    for kind in FEE_KINDS:
        register(f"RP_ECONOMY_FEE_{kind.upper()}", 0, validator=nonnegative)


def hook(name):
    value = getattr(settings, name, None)
    return resolve_dotted(value) if isinstance(value, str) else value


def is_staff(character):
    return bool(
        character.locks.check_lockstring(
            character, getattr(settings, "RP_ECONOMY_STAFF_LOCK", "cmd:perm(Builder)")
        )
    )


def visible(character):
    return get("RP_ECONOMY_REVEALED") or is_staff(character)


def currency(amount):
    nouns = getattr(settings, "RP_ECONOMY_CURRENCY", ("coin", "coins"))
    return f"{amount} {nouns[0] if amount == 1 else nouns[1]}"
