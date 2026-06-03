# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
+xp command for evennia_xp.

CmdXp — balance, award log, registered sources, and staff manual grant.

Usage:
    +xp                                  View your XP balance
    +xp/log                              View your last 20 XP awards
    +xp/log <N>                          View your last N awards (max 100)
    +xp/sources                          List registered XP sources
    +xp/grant <character>=<amt>:<reason> Award XP manually (staff)

Staff permission is governed by XP_STAFF_LOCK (default "cmd:perm(Builder)").

+spend and +upgrade are game-specific (XP spending ties into the ability
system).  They are not shipped here — implement them in your game's
commands and document them alongside +xp.
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        """Fallback when evennia-accessibility is not installed."""
        return False


_PAGE_SIZE = 20


def _staff_lock_expr():
    lock = getattr(settings, "XP_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


class CmdXp(MuxCommand):
    """
    View your XP balance, history, and registered sources.

    Usage:
        +xp                              View your balance
        +xp/log                          View your last 20 XP awards
        +xp/log <N>                      View your last N XP awards (max 100)
        +xp/sources                      List active XP sources
        +xp/grant <character>=<amt>:<reason>  Award XP manually (staff)

    XP is earned automatically every Monday from activities registered in
    XP_COLLECTORS. Use +xp/sources for a list of active sources.
    """

    key = "+xp"
    aliases = []  # noqa: RUF012
    help_category = "Character"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller

        if "grant" in self.switches:
            self._do_grant(caller)
        elif "log" in self.switches:
            self._do_log(caller, self.args.strip())
        elif "sources" in self.switches:
            self._do_sources(caller)
        else:
            self._do_balance(caller)

    # ------------------------------------------------------------------
    # +xp (balance view)
    # ------------------------------------------------------------------

    def _do_balance(self, caller):
        from evennia_xp.models import CharacterXP, XPLog

        sr = uses_screenreader(caller)

        try:
            xp = CharacterXP.objects.get(character_id=caller.pk)
            balance = xp.current_balance
            total_earned = xp.total_earned
            last_week = xp.last_payout_week or "—"
        except CharacterXP.DoesNotExist:
            balance = Decimal("0.00")
            total_earned = Decimal("0.00")
            last_week = "—"

        # Arc banner — shown if the active multiplier is below 1.0.
        downtime_banner = ""
        try:
            from evennia_xp.gating import resolve_xp_multiplier

            mult = resolve_xp_multiplier("rp_session")
            if mult < Decimal("1.0"):
                downtime_banner = (
                    f"|y[XP RATES MODIFIED: {mult}x]|n "
                    "XP rates are currently reduced. See +xp/sources."
                )
        except Exception:
            pass

        # Last payout breakdown (XPLog rows for the last payout week).
        last_payout_lines = []
        if last_week != "—":
            payout_logs = XPLog.objects.filter(character_id=caller.pk, week=last_week).order_by(
                "source_type"
            )
            by_source = {}
            for row in payout_logs:
                label = row.get_source_type_display()
                by_source[label] = by_source.get(label, Decimal("0.00")) + row.amount
            for src, amt in sorted(by_source.items()):
                last_payout_lines.append((src, f"+{amt}"))

        if sr:
            lines = [f"XP Balance for {caller.key}"]
            lines.append(f"Current balance: {balance} XP")
            lines.append(f"Total earned: {total_earned} XP")
            lines.append(f"Last payout week: {last_week}")
            if downtime_banner:
                lines.append(downtime_banner)
            if last_payout_lines:
                lines.append("")
                lines.append(f"Last payout ({last_week}):")
                for src, amt in last_payout_lines:
                    lines.append(f"  {src}: {amt}")
            lines.append("")
            lines.append("Use +xp/log to see your full award history.")
        else:
            sep = "-" * 50
            lines = [f"|wXP — {caller.key}|n", sep]
            if downtime_banner:
                lines.append(downtime_banner)
                lines.append(sep)
            lines.append(f"  Balance : |w{balance}|n XP  (total earned: {total_earned})")
            lines.append(f"  Last payout : {last_week}")
            if last_payout_lines:
                lines.append(sep)
                lines.append(f"  |wLast payout ({last_week})|n:")
                for src, amt in last_payout_lines:
                    lines.append(f"    {src:<20} {amt}")
            lines.append(sep)
            lines.append("  Use |w+xp/log|n to view history  |  |w+xp/sources|n for rates")

        caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # +xp/log [N]
    # ------------------------------------------------------------------

    def _do_log(self, caller, args):
        from evennia_xp.models import XPLog

        try:
            limit = max(1, min(int(args), 100)) if args else _PAGE_SIZE
        except (ValueError, TypeError):
            limit = _PAGE_SIZE

        logs = XPLog.objects.filter(character_id=caller.pk).order_by("-awarded_at")[:limit]

        if not logs:
            caller.msg("|wNo XP awards found.|n")
            return

        sr = uses_screenreader(caller)
        if sr:
            lines = [f"XP log for {caller.key} (last {limit})"]
            for row in logs:
                granted = f" (by {row.granted_by_name})" if row.granted_by_name else ""
                reason = f" — {row.reason}" if row.reason else ""
                lines.append(
                    f"  {row.awarded_at.strftime('%Y-%m-%d')} | "
                    f"+{row.amount} | {row.get_source_type_display()}"
                    f"{granted}{reason} | week {row.week}"
                )
        else:
            sep = "-" * 60
            lines = [f"|wXP Log — {caller.key}|n (last {limit})", sep]
            for row in logs:
                granted = f" |x(by {row.granted_by_name})|n" if row.granted_by_name else ""
                reason = f" {row.reason}" if row.reason else ""
                lines.append(
                    f"  {row.awarded_at.strftime('%Y-%m-%d')}  "
                    f"|w+{row.amount}|n  "
                    f"{row.get_source_type_display():<20}"
                    f"{granted}{reason}"
                )
            lines.append(sep)
            lines.append(f"  Showing {len(logs)} of your most recent awards.")

        caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # +xp/sources
    # ------------------------------------------------------------------

    def _do_sources(self, caller):
        sr = uses_screenreader(caller)
        registered = getattr(settings, "XP_COLLECTORS", [])

        # Current multiplier info (if a resolver is configured).
        mult_info = ""
        try:
            from evennia_xp.gating import resolve_xp_multiplier

            mult = resolve_xp_multiplier("rp_session")
            if mult != Decimal("1.0"):
                mult_info = f"  Current rp_session multiplier: {mult}x"
        except Exception:
            pass

        if sr:
            lines = ["XP Sources"]
            if registered:
                lines.append("Registered collectors:")
                for key, _ in registered:
                    lines.append(f"  {key}")
            else:
                lines.append("No XP collectors registered (XP_COLLECTORS is empty).")
            if mult_info:
                lines.append(mult_info)
            lines.append("")
            lines.append("No weekly cap. XP processed every Monday 00:00 UTC.")
        else:
            sep = "-" * 50
            lines = ["|wXP Sources|n", sep]
            if registered:
                lines.append("  |wRegistered collectors|n:")
                for key, _ in registered:
                    lines.append(f"    {key}")
            else:
                lines.append("  |xNo XP collectors registered.|n")
            if mult_info:
                lines.append(sep)
                lines.append(mult_info)
            lines.append(sep)
            lines.append("  No weekly cap. XP awarded every Monday at 00:00 UTC.")

        caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # +xp/grant <character>=<amount>:<reason>  (staff)
    # ------------------------------------------------------------------

    def _do_grant(self, caller):
        if not caller.locks.check_lockstring(caller, _staff_lock_expr()):
            caller.msg("|rYou need staff permission to grant XP.|n")
            return

        if not self.lhs or not self.rhs:
            caller.msg("Usage: +xp/grant <character>=<amount>:<reason>")
            return

        if ":" not in self.rhs:
            caller.msg("Usage: +xp/grant <character>=<amount>:<reason>")
            return

        amt_str, reason = self.rhs.split(":", 1)
        amt_str = amt_str.strip()
        reason = reason.strip()

        if not reason:
            caller.msg("|rA reason is required for manual XP grants.|n")
            return

        try:
            amount = Decimal(amt_str)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            caller.msg(f"|r'{amt_str}' is not a valid positive XP amount.|n")
            return

        target = caller.search(self.lhs.strip(), global_search=True)
        if not target:
            return

        from evennia_xp.awards import record_xp
        from evennia_xp.models import XPLog

        log = record_xp(
            character_id=target.pk,
            amount=amount,
            source_type=XPLog.SourceType.MANUAL_GRANT,
            source_ref_id=0,
            reason=reason,
            character_name=target.key,
            granted_by=caller,
        )

        caller.msg(
            f"|wGranted {amount} XP to {target.key}.|n  " f"Reason: {reason}  (XPLog #{log.pk})"
        )
        # Notify recipient if they're online.
        if target.has_account:
            target.msg(f"|w{caller.key} granted you {amount} XP.|n  Reason: {reason}")
