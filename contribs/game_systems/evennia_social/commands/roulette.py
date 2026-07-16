# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scene idea generator — +roulette command (stub).

A placeholder hook for games that want to suggest scene ideas from their
own plot/lore/region systems. This contrib ships the command shell only —
wiring it up to real content is entirely game-specific, so there is
nothing generic to implement here.
"""

from evennia.commands.default.muxcommand import MuxCommand


class CmdRoulette(MuxCommand):
    """
    Get a random scene idea suggestion.

    Usage:
        +roulette
        +roulette <region>

    Suggests an idea for a new scene. This is a stub — the consuming game
    is expected to override or extend this command to draw from its own
    plot threads, regions, and lore systems.
    """

    key = "+roulette"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        self.caller.msg("|w+roulette|n is not yet implemented.")
