# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web view for the XP summary page.

XPSummaryView — self-only balance, by-source breakdown, and paginated log.

Permission: login required + active puppet (require_character). Staff view
other characters' XP through Django admin.
"""

from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import ListView

from evennia_xp.models import CharacterXP, XPLog
from evennia_xp.permissions import get_character_id

try:
    from evennia_accessibility import uses_screenreader as _accessibility_sr
except ImportError:
    _accessibility_sr = None


class XPSummaryView(LoginRequiredMixin, ListView):
    """XP balance, lifetime by-source breakdown, and paginated log for the
    requesting character.

    Requires an active puppet (character_id). Anonymous and logged-in users
    without a puppet receive 403.
    """

    template_name = "evennia_xp/xp_summary.html"
    context_object_name = "logs"
    paginate_by = 50
    login_url = "/accounts/login/"

    def get_queryset(self):
        character_id = get_character_id(self.request.user)
        if not character_id:
            raise PermissionDenied("An active character is required to view XP.")
        return XPLog.objects.filter(character_id=character_id).order_by("-awarded_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        character_id = get_character_id(self.request.user)

        try:
            xp_row = CharacterXP.objects.get(character_id=character_id)
            balance = xp_row.current_balance
            total_earned = xp_row.total_earned
            total_spent = xp_row.total_spent
            last_payout_week = xp_row.last_payout_week
            character_name = xp_row.character_name
        except CharacterXP.DoesNotExist:
            balance = Decimal("0.00")
            total_earned = Decimal("0.00")
            total_spent = Decimal("0.00")
            last_payout_week = ""
            character_name = ""

        # By-source aggregation across all XP rows (not just the current page).
        all_logs = XPLog.objects.filter(character_id=character_id)
        by_source = {}
        for row in all_logs:
            label = row.get_source_type_display()
            by_source[label] = by_source.get(label, Decimal("0.00")) + row.amount
        by_source_sorted = sorted(by_source.items())

        # Screen-reader flag — passed to template for linear-list branch.
        sr = False
        if _accessibility_sr is not None:
            try:
                account = getattr(self.request.user, "account", None) or self.request.user
                sr = bool(_accessibility_sr(account))
            except Exception:
                pass

        # Arc banner via gating seam — shown when multiplier < 1.0.
        downtime_active = False
        xp_mult = Decimal("1.0")
        try:
            from evennia_xp.gating import resolve_xp_multiplier

            xp_mult = resolve_xp_multiplier("rp_session")
            downtime_active = xp_mult < Decimal("1.0")
        except Exception:
            pass

        context.update(
            {
                "page_title": "My XP",
                "character_name": character_name,
                "balance": balance,
                "total_earned": total_earned,
                "total_spent": total_spent,
                "last_payout_week": last_payout_week,
                "by_source": by_source_sorted,
                "screenreader_mode": sr,
                "downtime_active": downtime_active,
                "xp_mult": xp_mult,
            }
        )
        return context
