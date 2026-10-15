# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia.commands.default.muxcommand import MuxCommand

from . import conf
from .errors import CraftingError


class CraftCommand(MuxCommand):
    locks = "cmd:all()"
    help_category = "Crafting"
    wave_two = False
    wave_three = False

    def visible(self, actor):
        if self.wave_three:
            return conf.wave_three_visible(actor)
        return conf.wave_two_visible(actor) if self.wave_two else conf.visible(actor)

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        visible = self.visible(srcobj)
        return super().access(srcobj, access_type, default, **kwargs) and visible

    def func(self):
        if not self.visible(self.caller):
            return
        try:
            if len(self.switches) > 1:
                raise CraftingError("Use one switch at a time.")
            self.run(self.switches[0] if self.switches else "")
        except (CraftingError, ValueError) as exc:
            self.msg(str(exc))
