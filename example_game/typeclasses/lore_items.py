"""Host stock-deletion guards precede the reusable lore-tome implementation."""

from evennia_lore.items import LoreTome

from .objects import ObjectParent


class StaffTome(ObjectParent, LoreTome):
    pass
