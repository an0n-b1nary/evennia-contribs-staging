# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia import DefaultObject

from . import conf


class StallStock(DefaultObject):
    """An inaccessible container; transfers use the transactional stall service."""

    def at_object_creation(self):
        self.locks.add("get:false();puppet:false();view:false();delete:false()")

    def at_object_delete(self):
        return False

    def at_object_leave(self, moved_obj, target_location, **kwargs):
        if moved_obj.location != self:
            return super().at_object_leave(moved_obj, target_location, **kwargs)
        from .services import EconomyError

        raise EconomyError("Unlist or buy the item before moving stall stock.")


class EconomyObjectMixin:
    """Optional early deletion guard, before Evennia clears object attributes."""

    def at_object_delete(self):
        from .movement import guard_stock_deletion
        from .services import EconomyError

        try:
            guard_stock_deletion(None, self)
        except EconomyError as exc:
            self.msg(str(exc))
            return False
        return super().at_object_delete()


class MarketRoomMixin:
    """Place before the host room class; cooperative appearance, no fixed MRO peers."""

    def get_display_footer(self, looker, **kwargs):
        footer = super().get_display_footer(looker, **kwargs)
        if not conf.visible(looker):
            return footer
        from .models import Storefront

        stalls = Storefront.objects.filter(room=self, status="open").order_by("slot")
        roster = ", ".join(f"#{s.pk} {s.name}" for s in stalls)
        return "\n".join(part for part in (footer, f"Stalls: {roster}" if roster else "") if part)
