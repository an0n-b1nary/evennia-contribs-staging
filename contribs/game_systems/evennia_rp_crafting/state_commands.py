# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicit selection only: no activation, consumption, room output or RP credit."""

from . import states
from .command_base import CraftCommand
from .errors import CraftingError


class CmdAdjust(CraftCommand):
    """Select a wearable's crafter-authored cosmetic state.

    Usage:
      +adjust <carried item>
      +adjust <carried item> = <state name>

    Lists the current and available states, or selects one. Worn items obey
    the build lock. Selection persists through restart and transfer.
    """

    key = "+adjust"

    def run(self, switch):
        if switch or not self.lhs.strip():
            raise CraftingError("Usage: +adjust carried item [= state name]")
        item = self.caller.search(self.lhs.strip(), candidates=list(self.caller.contents))
        if item is None:
            return
        if self.rhs is None:
            data = states.inspect(self.caller, item)
            self.msg(
                f"{item.key}: {states.current(item, data)}. States: {', '.join(data['variants'])}."
            )
        else:
            key = states.select(self.caller, item, self.rhs)
            self.msg(f"You adjust {item.key}: {key}.")
