# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The equipment item, and the character mixin that shows what's worn.

Items::

    from evennia.objects.objects import DefaultObject
    from evennia_rp_equipment.typeclasses import EquipmentMixin

    class Gear(EquipmentMixin, ObjectParent, DefaultObject):
        ...

    RP_EQUIPMENT_TYPECLASS = "typeclasses.objects.Gear"

or use `evennia_rp_equipment.typeclasses.Equipment` as it is (the default).

Characters::

    class Character(EquipmentCharacterMixin, ObjectParent, DefaultCharacter):
        ...

`EquipmentCharacterMixin` only adds worn lines to the description and leaves
worn items out of the "You see" list. A game that can't take the mixin
unconditionally (equipment as an optional partner) calls
`display.with_worn()` and `display.hide_worn()` from its own overrides.
"""

from __future__ import annotations

from evennia.objects.objects import DefaultCharacter, DefaultObject
from evennia.typeclasses.attributes import AttributeProperty

WORN_TAG = "worn"
TAG_CATEGORY = "rp_equipment"
MAKER_CATEGORY = "rp_equipment_maker"

# Moves the default commands make; a worn item refuses all of them.
REFUSED_MOVES = ("get", "drop", "give")


class EquipmentMixin:
    """An item that can be worn, with a worn line, a slot and requirements.

    Worn means: tagged `worn` (category `rp_equipment`) and carried by the
    wearer. Requirements are stored as plain dicts (see `requirements`).
    """

    worn_line = AttributeProperty(default="", autocreate=False)
    slot = AttributeProperty(default="", autocreate=False)
    requirement_data = AttributeProperty(default=None, autocreate=False)
    maker_id = AttributeProperty(default=None, autocreate=False)
    maker_name = AttributeProperty(default="", autocreate=False)
    # Set once a character other than the maker holds it; requirements and
    # prose are fixed from then on.
    sealed = AttributeProperty(default=False, autocreate=False)

    @property
    def is_worn(self) -> bool:
        return self.tags.has(WORN_TAG, category=TAG_CATEGORY)

    @property
    def wearer(self):
        return self.location if self.is_worn else None

    def get_requirements(self) -> list:
        from evennia_rp_equipment.requirements import Requirement

        return [Requirement.from_dict(data) for data in self.requirement_data or ()]

    def get_worn_line(self, looker=None) -> str:
        return self.worn_line or self.get_display_name(looker)

    # -- staying put while worn -----------------------------------------------

    def _refuse_while_worn(self, actor) -> bool:
        if self.is_worn:
            if actor is not None:
                actor.msg(f"Remove {self.get_display_name(actor)} first.")
            return True
        return False

    def at_pre_get(self, getter, **kwargs):
        return not self._refuse_while_worn(getter) and super().at_pre_get(getter, **kwargs)

    def at_pre_drop(self, dropper, **kwargs):
        return not self._refuse_while_worn(dropper) and super().at_pre_drop(dropper, **kwargs)

    def at_pre_give(self, giver, getter, **kwargs):
        return not self._refuse_while_worn(giver) and super().at_pre_give(giver, getter, **kwargs)

    def at_pre_move(self, destination, move_type="move", **kwargs):
        # Backstop for code that moves things without the default commands' hooks.
        if self.is_worn and move_type in REFUSED_MOVES:
            return False
        return super().at_pre_move(destination, move_type=move_type, **kwargs)

    def at_post_move(self, source_location, move_type="move", **kwargs):
        # Our own state first, so a failing hook further along the MRO can't
        # leave a handed-over item editable by its maker.
        # Staff can still teleport a worn item away; it isn't worn any more.
        if self.is_worn and self.location is not source_location:
            self.tags.remove(WORN_TAG, category=TAG_CATEGORY)
        holder = self.location
        if isinstance(holder, DefaultCharacter) and holder.id != self.maker_id:
            self.sealed = True
        super().at_post_move(source_location, move_type=move_type, **kwargs)


class Equipment(EquipmentMixin, DefaultObject):
    """The default equipment typeclass."""


class EquipmentCharacterMixin:
    """Worn lines in the description; worn items left out of "You see"."""

    def get_display_desc(self, looker, **kwargs):
        from evennia_rp_equipment.display import with_worn

        return with_worn(self, looker, super().get_display_desc(looker, **kwargs))

    def filter_visible(self, obj_list, looker, **kwargs):
        from evennia_rp_equipment.display import hide_worn

        return hide_worn(super().filter_visible(obj_list, looker, **kwargs))


__all__ = [
    "Equipment",
    "EquipmentCharacterMixin",
    "EquipmentMixin",
]
