# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Validate raw command switches before MuxCommand parses them."""


class SingleSwitchMixin:
    """Validate raw switches before MuxCommand can discard an invalid one."""

    switch_options = ()
    retired_switches = ()

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
        if switch in self.retired_switches or len(matches) != 1:
            self.msg(f"Unknown or ambiguous switch. See help {self.key} for usage.")
            return True
        self.args = f"/{switch}" + (f" {tail[0]}" if tail else "")
        return False
