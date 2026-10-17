# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persisted wearables become ordinary crafted objects without equipment."""

from django.apps import apps
from evennia.objects.objects import DefaultObject

from .typeclasses import CraftedItemMixin

if apps.is_installed("evennia_rp_equipment"):
    from evennia_rp_equipment.typeclasses import EquipmentMixin
else:

    class EquipmentMixin:
        def get_worn_line(self, looker=None):
            return self.db.worn_line or self.key


class Wearable(CraftedItemMixin, EquipmentMixin, DefaultObject):
    def get_worn_line(self, looker=None):
        from .item_display import equipment_renders, render

        line = super().get_worn_line(looker)
        if not equipment_renders(self):
            line = render(self, looker, "worn", line)
        record = self.craft_record
        aura = record.prose["configuration"].get("aura_line", "") if record else ""
        return f"{line}\n  {aura}" if aura else line
