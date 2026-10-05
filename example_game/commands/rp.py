"""The game's command names for the optional RP character-build contrib."""

from evennia_rp_chargen.commands import CmdPips


class CmdEdge(CmdPips):
    """Manage Edge and Weakness pips.

    Usage:
      +edge
      +edge/set <stat>=<count>
      +edge/clear [<stat>]
      +edge/weakness <stat>=<count>

    Counts can be numbers or pips (+++ or --). Your Edge budget is shared
    across stats. +unlock first when your build is locked for a scene.
    """

    key = "+edge"
    aliases = ("+pips",)
