# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One-switch commands validated before MuxCommand discards unknown switches."""


class SingleSwitchMixin:
    """Validate raw switches before MuxCommand can discard an invalid one."""

    switch_options = ()

    def at_pre_cmd(self):
        if super().at_pre_cmd():
            return True
        raw = self.args.strip()
        if not raw.startswith("/"):
            return False
        head, *tail = raw.split(maxsplit=1)
        switch = head[1:].lower()
        if "/" in switch:
            self.msg("Use one switch at a time.")
            return True
        matches = [option for option in self.switch_options if option == switch] or [
            option for option in self.switch_options if option.startswith(switch)
        ]
        if len(matches) != 1:
            self.msg(f"Unknown or ambiguous switch. See help {self.key} for usage.")
            return True
        self.args = f"/{switch}" + (f" {tail[0]}" if tail else "")
        return False


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
