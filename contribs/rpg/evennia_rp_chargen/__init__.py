# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rp_chargen — character sheets on the evennia_rp_rules kernel.

Graded stats chosen within an allocation (point-buy, array or free), edge and
weakness pips under a pip policy, a draft -> finalized (-> approved) life
cycle, and build locks that freeze edge and loadout while a character is in a
scene. Stat names, rungs and numbers all come from the game's ruleset.

Modules:

    services   — every sheet change, with policy applied (raises ChargenError)
    stats      — StatHandler: ratings stored on the character
    allocation — FreeAllocation, PointBuyAllocation, ArrayAllocation
    pips       — PipPolicy: edge budget and caps, weakness caps
    locks      — note_ic_action, lock, unlock, release
    subject    — ChargenSubject and subject_adapter for checks
    sheet      — render_sheet
    commands   — +sheet, +stats, +pips, +lock, +unlock, +chargen

Importing the package imports no models; import the modules you need.
"""

__version__ = "0.2.0"
