# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rp_equipment — wearable gear that asks for a build commitment and grants nothing.

Anyone can make a plain item with a description, a worn line and a slot.
Requirements tie wearing it to the wearer's evennia_rp_chargen build: + pips
or weakness on a stat, an equipped ability, a held flaw. While the item is
worn, chargen's change guard refuses the build changes it depends on, and
wearing or removing freezes whenever the build is locked.

Modules:

    requirements — Requirement, parse, describe, status
    services     — make, edit, wear and remove (raises GearError)
    typeclasses  — EquipmentMixin, Equipment, EquipmentCharacterMixin
    display      — worn_items, with_worn, hide_worn
    guard        — the build_change_requested receiver
    audit        — worn gear whose requirements no longer hold
    commands     — +gear, +wear, +remove, +worn

Importing the package imports no models; import the modules you need.
"""

__version__ = "0.1.2"
