# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Put CraftedItemMixin before the host object/equipment class in its MRO."""

from evennia.objects.objects import DefaultObject


class ModificationDisplayMixin:
    """Place before the host object/character; base prose remains host-owned."""

    def get_display_desc(self, looker, **kwargs):
        from .item_display import equipment_renders, render

        desc = super().get_display_desc(looker, **kwargs)
        return desc if equipment_renders(self) else render(self, looker, "desc", desc)


class CraftedItemMixin(ModificationDisplayMixin):
    @property
    def craft_record(self):
        from .models import CraftRecord

        return CraftRecord.objects.filter(item_id=self.pk).first()

    def get_display_provenance(self, looker=None):
        """Verified provenance comes from the immutable record, never item prose."""
        record = self.craft_record
        if record is None:
            return ""
        from .readables import provenance

        return provenance(record)

    def get_market_keywords(self, looker=None):
        record = self.craft_record
        if record is None:
            return []
        return [
            *(value for row in record.contributor_data for value in (row["key"], row["name"])),
            *record.behaviour_keys,
        ]

    def read(self, reader, page=None, *, contents=False):
        from .pages import read

        return read(reader, self, page, table=contents)

    def get_display_recognition(self, looker):
        from .facets import display

        return display(self, looker)

    def get_display_desc(self, looker, **kwargs):
        desc = super().get_display_desc(looker, **kwargs)
        recognition = self.get_display_recognition(looker)
        from .letters import display

        record = self.craft_record
        if record and looker is not None and self.access(looker, "view", default=True):
            letter = display(record)
            if letter:
                desc = f"{desc}\n\n{letter}"
        if recognition:
            desc = f"{desc}\n{recognition}"
        hallmark = self.get_display_provenance(looker)
        return f"{desc}\n\n|wCraft hallmark (OOC):|n {hallmark}" if hallmark else desc


class Readable(CraftedItemMixin, DefaultObject):
    """Carried lifecycle, retaining the original public typeclass path."""


class Consumable(CraftedItemMixin, DefaultObject):
    """Only a verified craft record can authorize this item's EVENT."""

    def use(self, actor):
        from .events import use

        return use(actor, self)


class Broadcast(Consumable):
    """Consumable whose EVENT also reaches adjacent rooms."""


class Installable(CraftedItemMixin, DefaultObject):
    """Installed fixtures move only through the owner-authorized service."""

    def at_pre_get(self, getter, **kwargs):
        from .models import FixtureInstallation

        if FixtureInstallation.objects.filter(craft__item_id=self.pk, active=True).exists():
            getter.msg(
                "That fixture is installed. Ask the property owner or staff to uninstall it."
            )
            return False
        return super().at_pre_get(getter, **kwargs)

    def at_pre_move(self, destination, **kwargs):
        from .models import FixtureInstallation

        if (
            not self.ndb.crafting_placement
            and FixtureInstallation.objects.filter(craft__item_id=self.pk, active=True).exists()
        ):
            return False
        return super().at_pre_move(destination, **kwargs)

    def at_object_delete(self):
        from .models import FixtureInstallation

        if FixtureInstallation.objects.filter(craft__item_id=self.pk, active=True).exists():
            return False
        return super().at_object_delete()


class CraftingRoomMixin:
    """Place before the host room; preserve its prose and release fixtures on delete."""

    def get_display_desc(self, looker, **kwargs):
        from .fixtures import layers

        base = super().get_display_desc(looker, **kwargs)
        return "\n".join([base, *layers(self)])

    def at_object_delete(self):
        allowed = super().at_object_delete()
        if allowed:
            from .fixtures import release_room

            release_room(self)
        return allowed
