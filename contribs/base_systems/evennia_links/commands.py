# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff controls for explicitly registered runtime settings."""

import json

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand

from . import runtime


class CmdRuntime(MuxCommand):
    """List/set runtime controls using JSON values.

    Usage:
      +runtime [NAME]
      +runtime NAME=<JSON value>
      +runtime/reset NAME

    Only registered controls can be changed. Reset restores the host setting.
    """

    key = "+runtime"
    locks = "cmd:all()"
    help_category = "Building"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super().access(
            srcobj, access_type, default, **kwargs
        ) and srcobj.locks.check_lockstring(
            srcobj, getattr(settings, "LINKS_RUNTIME_STAFF_LOCK", "cmd:perm(Builder)")
        )

    def func(self):
        if not self.access(self.caller):
            self.msg("Only staff may change runtime controls.")
            return
        try:
            name = self.lhs.strip()
            if self.switches == ["reset"]:
                runtime.reset(name, by=self.caller)
                self.msg(f"{name} reset to {runtime.get(name)!r}.")
            elif self.switches:
                self.msg("Usage: +runtime [NAME[=<JSON value>]] or +runtime/reset NAME")
            elif self.rhs is not None:
                runtime.set(name, json.loads(self.rhs), by=self.caller)
                self.msg(f"{name} = {runtime.get(name)!r}")
            else:
                names = [name] if name else sorted(runtime.registered())
                self.msg(
                    "\n".join(f"{key} = {runtime.get(key)!r}" for key in names)
                    or "No controls registered."
                )
        except (ValueError, TypeError) as exc:
            self.msg(str(exc))
