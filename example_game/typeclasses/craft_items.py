"""Host deletion guards run before crafting/equipment/DefaultObject hooks."""

from evennia_rp_crafting.typeclasses import Broadcast, Consumable, Readable
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
