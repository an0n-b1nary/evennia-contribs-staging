# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional stock-look extension for named crafted item details."""

from evennia.commands.default.general import CmdLook as DefaultLook

from evennia_links.command_syntax import StrictSwitchMixin

from . import conf
from .errors import CraftingError
from .item_details import examine, local_items


class CmdLook(StrictSwitchMixin, DefaultLook):
    """Look normally, or examine a named detail on a local crafted item.

    Usage:
      look
      look <object>
      look <item> = <detail name>
      look <item> <detail name>

    A complete object name takes precedence over the space-separated detail
    form. Use = to disambiguate. Ordinary looking retains the stock command.
    """

    def func(self):
        if not self.args or not conf.visible(self.caller):
            return super().func()
        if self.caller.search(self.args, quiet=True):
            return super().func()
        candidates = local_items(self.caller)
        item_name, name = self.lhs, self.rhs
        if name is None:
            parts = self.args.split()
            for index in range(len(parts) - 1, 0, -1):
                prefix = " ".join(parts[:index])
                if self.caller.search(prefix, candidates=candidates, quiet=True):
                    item_name, name = prefix, " ".join(parts[index:])
                    break
            else:
                return super().func()
        item = self.caller.search(item_name.strip(), candidates=candidates)
        if item is None:
            return
        try:
            result = examine(self.caller, item, name)
        except CraftingError as exc:
            self.msg(str(exc))
            return
        self.msg(text=(f"{item.key} — {name.strip()}\n{result}", {"type": "look"}))
