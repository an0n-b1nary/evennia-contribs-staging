# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Showing what a character wears.

`EquipmentCharacterMixin` calls these. A game that installs equipment as an
optional partner calls them from its own Character overrides instead::

    def get_display_desc(self, looker, **kwargs):
        desc = super().get_display_desc(looker, **kwargs)
        if apps.is_installed("evennia_rp_equipment"):
            from evennia_rp_equipment.display import with_worn

            desc = with_worn(self, looker, desc)
        return desc
"""

from __future__ import annotations

from evennia_rp_equipment import conf


def is_equipment(obj) -> bool:
    from evennia_rp_equipment.typeclasses import EquipmentMixin

    return isinstance(obj, EquipmentMixin)


def _slot_order(item) -> tuple:
    slots = conf.slots()
    slot = (item.slot or "").lower()
    return (slots.index(slot) if slot in slots else len(slots), slot, item.key.lower())


def worn_items(character) -> list:
    """What `character` wears, in slot order (unlisted slots last, then by name)."""
    items = [obj for obj in character.contents if is_equipment(obj) and obj.is_worn]
    return sorted(items, key=_slot_order)


def worn_lines(character, looker=None) -> list[str]:
    return [item.get_worn_line(looker) for item in worn_items(character)]


def with_worn(character, looker, desc: str) -> str:
    """`desc` followed by what `character` wears, if anything."""
    lines = worn_lines(character, looker)
    if not lines:
        return desc
    return desc + "\n\n|wWearing:|n\n" + "\n".join(f"  {line}" for line in lines)


def hide_worn(objects) -> list:
    """`objects` without worn items: they're described by their worn lines instead."""
    return [obj for obj in objects if not (is_equipment(obj) and obj.is_worn)]


__all__ = ["hide_worn", "is_equipment", "with_worn", "worn_items", "worn_lines"]
