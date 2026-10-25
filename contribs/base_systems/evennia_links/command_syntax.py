# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Validate command input before Evennia can discard a mistyped switch."""


class StrictSwitchMixin:
    """Refuse unknown, ambiguous and stacked switches before parsing or lookup.

    Put this before the Evennia command base. Declare every accepted switch in
    ``switch_options``; an empty tuple means the command takes no switches.
    Exact matches win over unique prefixes, as in MuxCommand.
    """

    def at_pre_cmd(self):
        raw = self.args.strip()
        if raw.startswith("/"):
            head, *tail = raw.split(maxsplit=1)
            switch = head[1:].lower()
            options = getattr(self, "switch_options", ()) or ()
            matches = [option for option in options if option == switch] or [
                option for option in options if option.startswith(switch)
            ]
            if "/" in switch:
                # Bypass subject-aware msg overrides: even attribution can query
                # NPC state, and a syntax refusal must precede those lookups.
                super().msg(f"Use one switch at a time. See help {self.key} for usage.")
                return True
            if not switch or switch in getattr(self, "retired_switches", ()) or len(matches) != 1:
                super().msg(f"Unknown or ambiguous switch. See help {self.key} for usage.")
                return True
            # MuxCommand's switch matching is case-sensitive; preserve the rest.
            self.args = f"/{matches[0]}" + (f" {tail[0]}" if tail else "")
        return super().at_pre_cmd()


def whole_number(value, noun="number"):
    """Convert a command's number, with a refusal suitable for a player."""
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"Give a whole {noun}.") from None
