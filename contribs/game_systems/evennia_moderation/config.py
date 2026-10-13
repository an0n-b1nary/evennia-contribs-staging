# SPDX-License-Identifier: BSD-3-Clause
from evennia_links.runtime import get, register

DEFAULTS = {
    "MODERATION_PLAYER_CAP": (None, lambda v: v is None or (type(v) is int and v >= 0)),
    "MODERATION_REFERRAL_MODE": ("optional", lambda v: v in ("off", "optional", "required")),
    "MODERATION_REFERRAL_ALLOWANCE": (0, lambda v: type(v) is int and v >= 0),
    "MODERATION_CODE_DAYS": (14, lambda v: type(v) is int and v > 0),
    "MODERATION_APPLICATION_DAYS": (14, lambda v: type(v) is int and v > 0),
    "MODERATION_INTAKE_CLOSED": (False, lambda v: type(v) is bool),
    "MODERATION_CLOSED_MESSAGE": (
        "Applications are currently closed.",
        lambda v: isinstance(v, str) and bool(v.strip()),
    ),
    "MODERATION_SOFTBAN_HOURS": (48, lambda v: type(v) is int and v > 0),
    "MODERATION_STAFF_LOCK": (
        "cmd:perm(Builder)",
        lambda v: isinstance(v, str) and bool(v.strip()),
    ),
}


def register_settings():
    for name, (default, validator) in DEFAULTS.items():
        register(
            name,
            default,
            validator=validator,
            description=name.removeprefix("MODERATION_").replace("_", " ").lower(),
        )


def value(name):
    return get("MODERATION_" + name)
