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


def covered_slots(character) -> set[str]:
    """Slots hidden by actually worn gear, including gear under another layer.

    A hidden cloak still covers the shirt underneath it. Merely configuring a
    cloak->body rule doesn't hide anything until a cloak is worn.
    """
    rules = conf.slot_covers()
    return {target for item in worn_items(character) for target in rules.get(item.slot, ())}


def visible_worn_items(character) -> list:
    """Visible worn gear for ordinary looks; never use this list for build guards."""
    hidden = covered_slots(character)
    return [item for item in worn_items(character) if item.slot not in hidden]


def worn_lines(character, looker=None, *, include_covered=False) -> list[str]:
    items = worn_items(character) if include_covered else visible_worn_items(character)
    return [item.get_worn_line(looker) for item in items]


def with_worn(character, looker, desc: str) -> str:
    """`desc` followed by what `character` wears, if anything."""
    lines = worn_lines(character, looker)
    if not lines:
        return desc
    return desc + "\n\n|wWearing:|n\n" + "\n".join(f"  {line}" for line in lines)


def hide_worn(objects) -> list:
    """`objects` without worn items: they're described by their worn lines instead."""
    return [obj for obj in objects if not (is_equipment(obj) and obj.is_worn)]


__all__ = [
    "covered_slots",
    "hide_worn",
    "is_equipment",
    "visible_worn_items",
    "with_worn",
    "worn_items",
    "worn_lines",
]
