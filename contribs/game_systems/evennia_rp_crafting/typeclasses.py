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
        return [record.niche.key, record.niche_name, record.behaviour] if record else []

    def get_display_desc(self, looker, **kwargs):
        desc = super().get_display_desc(looker, **kwargs)
        hallmark = self.get_display_provenance(looker)
        return f"{desc}\n\n|wCraft hallmark:|n {hallmark}" if hallmark else desc


class Readable(CraftedItemMixin, DefaultObject):
    """A crafted container of text; its contents are read from the craft record."""

    def read(self, reader):
        from .errors import CraftingError

        record = self.craft_record
        if record is None or record.behaviour != "readable":
            raise CraftingError("There is nothing written here.")
        if not self.access(reader, "read", default=True):
            raise CraftingError("You cannot read that.")
        return record.prose["configuration"]["text"]


class Consumable(CraftedItemMixin, DefaultObject):
    """Only a verified craft record can authorize this item's EVENT."""

    def use(self, actor):
        from .events import use

        return use(actor, self)


class Broadcast(Consumable):
    """Consumable whose EVENT also reaches adjacent rooms."""
