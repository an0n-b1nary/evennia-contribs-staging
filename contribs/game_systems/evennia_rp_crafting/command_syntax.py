# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One-switch commands validated before MuxCommand discards unknown switches."""

from evennia_links.command_syntax import StrictSwitchMixin as SingleSwitchMixin  # noqa: F401


def bare_value(command):
    """No-target fields retain authored punctuation but reject the old leading =."""
    from .errors import CraftingError

    value = command.args.strip()
    if value.startswith("="):
        raise CraftingError(f"Usage: {command.key}/{command.switches[0]} <value>")
    return value


def resource_amount(value):
    """One positive whole amount and resource key; selection never spends."""
    from evennia_rp_resources import services as resources

    from . import conf
    from .errors import CraftingError

    parts = value.strip().split()
    if len(parts) != 2 or not parts[0].isascii() or not parts[0].isdecimal():
        raise CraftingError("Select one resource as <quantity> <resource key>, e.g. 2 timber.")
    amount, key = int(parts[0]), parts[1]
    if not conf.positive(amount):
        raise CraftingError("Choose a positive whole resource quantity within the supported range.")
    try:
        resources.definition(key)
    except resources.ResourceError as exc:
        raise CraftingError(str(exc)) from None
    return key, amount


def select_resource(draft, value, *, remove=False):
    from .errors import CraftingError

    selected = dict(draft.get("selected", {}))
    if remove:
        key = value.strip()
        if key not in selected:
            raise CraftingError("That resource is not selected.")
        del selected[key]
    else:
        key, amount = resource_amount(value)
        selected[key] = amount
    draft["selected"] = selected
