"""Host deletion guards run before crafting/equipment/DefaultObject hooks."""

from evennia_rp_crafting.companions import CompanionObject
from evennia_rp_crafting.typeclasses import Broadcast, Consumable, Installable, Readable
from evennia_rp_crafting.wearables import Wearable

from .objects import ObjectParent


class CraftedBook(ObjectParent, Readable):
    pass


class CraftedWearable(ObjectParent, Wearable):
    pass


class CraftedConsumable(ObjectParent, Consumable):
    pass


class CraftedBroadcast(ObjectParent, Broadcast):
    pass


class CraftedFixture(ObjectParent, Installable):
    pass


class CraftedCompanion(ObjectParent, CompanionObject):
    """Host stock guards run before Companion/DefaultObject deletion hooks."""
