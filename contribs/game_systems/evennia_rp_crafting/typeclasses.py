# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Put CraftedItemMixin before the host object/equipment class in its MRO."""

from evennia.objects.objects import DefaultObject


class CraftedItemMixin:
    @property
    def craft_record(self):
        from .models import CraftRecord

        return CraftRecord.objects.filter(item_id=self.pk).first()

    def get_display_provenance(self, looker=None):
        """Verified provenance comes from the immutable record, never item prose."""
        record = self.craft_record
        return record.hallmark if record else ""

    def get_market_keywords(self, looker=None):
        record = self.craft_record
        if record is None:
            return []
        return [
            *(value for row in record.contributor_data for value in (row["key"], row["name"])),
            *record.behaviour_keys,
        ]

    def read(self, reader):
        from .composition import invoke

        return invoke(reader, self, "readable")

    def get_display_desc(self, looker, **kwargs):
        desc = super().get_display_desc(looker, **kwargs)
        hallmark = self.get_display_provenance(looker)
        return f"{desc}\n\n|wCraft hallmark:|n {hallmark}" if hallmark else desc


class Readable(CraftedItemMixin, DefaultObject):
    """Carried lifecycle, retaining the original public typeclass path."""


class Consumable(CraftedItemMixin, DefaultObject):
    """Only a verified craft record can authorize this item's EVENT."""

    def use(self, actor):
        from .events import use

        return use(actor, self)


class Broadcast(Consumable):
    """Consumable whose EVENT also reaches adjacent rooms."""
