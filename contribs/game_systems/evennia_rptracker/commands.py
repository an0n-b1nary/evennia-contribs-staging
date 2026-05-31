# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
RP activity tracking commands.

Player command for viewing session history and manually ending sessions.
Staff command for reviewing activity patterns and flagging suspicious sessions.

Add to your CharacterCmdSet::

    from evennia_rptracker.commands import CmdActivity, CmdRPTrackerStaff
    self.add(CmdActivity)
    self.add(CmdRPTrackerStaff)

Optional hooks (configure in settings.py):
  RPTRACKER_XP_PROJECTION  — callable(character_pk, window_end) -> list[str] | None
  RPTRACKER_SCENE_DISPLAY  — callable(scene_id) -> str
  RPTRACKER_STAFF_LOCK     — lock string for CmdRPTrackerStaff (default "cmd:perm(Builder)")
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand


def _resolve_dotted(dotted_path):
    """Import and return a callable from a dotted module path, or None."""
    if not dotted_path:
        return None
    try:
        from django.utils.module_loading import import_string

        return import_string(dotted_path)
    except Exception:
        import logging

        logging.getLogger("evennia").exception("rptracker: failed to import hook %r", dotted_path)
        return None


def _iso_week(dt):
    """Return ISO week string like '2026-W14' for a datetime."""
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"


def _format_session_row(session, show_char=False):
    """Return a single display line for an RPSession."""
    status_colors = {
        "active": "|g",
        "pending": "|y",
        "completed": "|w",
        "flagged": "|r",
    }
    color = status_colors.get(session.status, "|n")
    status_tag = f"{color}[{session.get_status_display()}]|n"
    duration = session.duration_display()
    partners = session.partners.count()
    flag = " |r[FLAGGED]|n" if session.status == "flagged" else ""
    prefix = f"{session.character_name}: " if show_char else ""
    return (
        f"  #{session.pk} {prefix}{status_tag} "
        f"{duration} | {session.pose_count} poses | {partners} partner(s)"
        f"{flag}"
    )


class CmdActivity(MuxCommand):
    """
    View your RP session activity and manually end sessions.

    Usage:
        +activity              - View your RP sessions this week
        +activity/history      - View past 4 weeks
        +activity/history <N>  - View past N weeks
        +activity/detail <id>  - View details of a specific session
        +activity/end          - Manually end your current RP session

    The RPTracker passively detects RP activity — you don't need to start
    or stop anything manually. Using /end explicitly closes your current
    session and records it as manually ended. Repeatedly ending and
    restarting sessions may be flagged for staff review.
    """

    key = "+activity"
    aliases = []  # noqa: RUF012
    help_category = "Character"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        switches = self.switches
        args = self.args.strip()

        if "end" in switches:
            self._do_end(caller)
        elif "detail" in switches:
            self._do_detail(caller, args)
        elif "history" in switches:
            self._do_history(caller, args)
        else:
            self._do_current_week(caller)

    def _do_end(self, caller):
        from evennia_rptracker.tracker import end_session, get_active_session_id

        session_id = get_active_session_id(caller.id)
        if not session_id:
            caller.msg("|wYou have no active RP session to end.|n")
            return
        end_session(caller.id, manual=True)
        caller.msg("|wYour RP session has been ended manually.|n")

    def _do_detail(self, caller, args):
        from evennia_rptracker.models import RPSession

        if not args or not args.isdigit():
            caller.msg("Usage: +activity/detail <session id>")
            return

        try:
            session = RPSession.objects.get(pk=int(args), character=caller)
        except RPSession.DoesNotExist:
            caller.msg(f"|wNo session #{args} found for your character.|n")
            return

        lines = [
            f"|wSession #{session.pk}|n",
            f"  Status   : {session.get_status_display()}",
            f"  Duration : {session.duration_display()}",
            f"  Poses    : {session.pose_count}",
            f"  Room     : {session.room_name or '(unknown)'}",
            f"  Started  : {session.started_at.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if session.ended_at:
            lines.append(f"  Ended    : {session.ended_at.strftime('%Y-%m-%d %H:%M')} UTC")
        if session.ended_manually:
            lines.append("  |y(Ended manually)|n")

        partners = list(session.partners.all())
        if partners:
            plist = ", ".join(p.partner_name or "(unknown)" for p in partners)
            lines.append(f"  Partners : {plist}")
        else:
            lines.append("  Partners : (none recorded)")

        render_scene = _resolve_dotted(getattr(settings, "RPTRACKER_SCENE_DISPLAY", None))
        scene_links = list(session.scene_links.all())
        if scene_links:
            scene_strs = []
            for link in scene_links:
                if render_scene:
                    scene_strs.append(render_scene(link.scene_id))
                else:
                    scene_strs.append(f"Scene #{link.scene_id}")
            lines.append(f"  Scenes   : {', '.join(scene_strs)}")
        else:
            lines.append("  Scenes   : (none linked)")

        if session.status == "flagged":
            lines.append(f"  |r[FLAGGED]|n: {session.flag_reason}")

        caller.msg("\n".join(lines))

    def _do_history(self, caller, args):
        from datetime import timedelta

        from django.utils import timezone

        from evennia_rptracker.models import RPSession

        try:
            weeks = int(args) if args else 4
            weeks = max(1, min(weeks, 52))
        except ValueError:
            weeks = 4

        cutoff = timezone.now() - timedelta(weeks=weeks)
        sessions = RPSession.objects.filter(
            character=caller,
            started_at__gte=cutoff,
        ).exclude(status=RPSession.Status.PENDING)

        if not sessions.exists():
            caller.msg(f"|wNo sessions found in the past {weeks} week(s).|n")
            return

        header = f"|wRP Sessions — past {weeks} week(s)|n"
        lines = [header, "-" * 50]
        for s in sessions:
            lines.append(_format_session_row(s))
        caller.msg("\n".join(lines))

    def _do_current_week(self, caller):
        from datetime import timedelta

        from django.utils import timezone

        from evennia_rptracker.models import RPSession
        from evennia_rptracker.tracker import get_session_state

        now = timezone.now()
        week_str = _iso_week(now)

        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        sessions = RPSession.objects.filter(
            character=caller,
            started_at__gte=week_start,
        ).exclude(status=RPSession.Status.PENDING)

        header = f"|wYour RP Activity — {week_str}|n"
        lines = [header, "-" * 50]

        live_state = get_session_state(caller.id)
        if live_state and live_state["status"] == "active":
            import time

            elapsed = int(time.time() - live_state["started_at"])
            h, r = divmod(elapsed, 3600)
            m = r // 60
            dur_str = f"{h}h {m}m" if h else f"{m}m"
            lines.append(
                f"  |g[ACTIVE SESSION]|n {dur_str} in progress "
                f"({live_state['pose_count']} poses, "
                f"{len(live_state['partner_pose_counts'])} partner(s) seen)"
            )
        elif live_state and live_state["status"] == "pending":
            lines.append("  |y[PENDING]|n Posing detected; waiting for partner to activate.")

        if sessions.exists():
            for s in sessions:
                lines.append(_format_session_row(s))
        else:
            if not live_state:
                lines.append("  No RP sessions detected this week.")

        provider = _resolve_dotted(getattr(settings, "RPTRACKER_XP_PROJECTION", None))
        if provider:
            extra = provider(caller.pk, now)
            if extra:
                lines.extend(extra)

        caller.msg("\n".join(lines))


class CmdRPTrackerStaff(MuxCommand):
    """
    Review RP session activity for anti-gaming detection (staff).

    Usage:
        +rptracker/review              - Show recent sessions with flags
        +rptracker/flag <id>=<reason>  - Flag a session as suspicious
        +rptracker/unflag <id>         - Remove a flag from a session

    Flagged sessions are excluded from XP until reviewed. Flags are
    per-session — a player's other legitimate sessions are unaffected.
    """

    key = "+rptracker"
    aliases = []  # noqa: RUF012
    help_category = "Staff"
    locks = getattr(settings, "RPTRACKER_STAFF_LOCK", "cmd:perm(Builder)")

    def func(self):
        switches = self.switches
        args = self.args.strip()

        if "flag" in switches:
            self._do_flag(args)
        elif "unflag" in switches:
            self._do_unflag(args)
        else:
            self._do_review()

    def _do_flag(self, args):
        if "=" not in args:
            self.caller.msg("Usage: +rptracker/flag <id>=<reason>")
            return

        id_part, reason = args.split("=", 1)
        id_part = id_part.strip()
        reason = reason.strip()

        if not id_part.isdigit():
            self.caller.msg("Session ID must be a number.")
            return
        if not reason:
            self.caller.msg("Please provide a reason.")
            return

        from evennia_rptracker.models import RPSession

        try:
            session = RPSession.objects.get(pk=int(id_part))
        except RPSession.DoesNotExist:
            self.caller.msg(f"|wNo session #{id_part} found.|n")
            return

        session.flag(reason=reason, flagged_by=self.caller)
        self.caller.msg(f"|wSession #{session.pk} ({session.character_name}) flagged.|n")

    def _do_unflag(self, args):
        if not args or not args.isdigit():
            self.caller.msg("Usage: +rptracker/unflag <id>")
            return

        from evennia_rptracker.models import RPSession

        try:
            session = RPSession.objects.get(pk=int(args))
        except RPSession.DoesNotExist:
            self.caller.msg(f"|wNo session #{args} found.|n")
            return

        if session.status != RPSession.Status.FLAGGED:
            self.caller.msg(
                f"|wSession #{session.pk} is not flagged "
                f"(status: {session.get_status_display()}).|n"
            )
            return

        session.unflag()
        self.caller.msg(f"|wSession #{session.pk} ({session.character_name}) unflagged.|n")

    def _do_review(self):
        from datetime import timedelta

        from django.utils import timezone

        from evennia_rptracker.models import RPSession
        from evennia_rptracker.tracker import _active_sessions

        now = timezone.now()
        cutoff = now - timedelta(days=7)

        flagged = RPSession.objects.filter(status=RPSession.Status.FLAGGED).order_by("-flagged_at")[
            :20
        ]
        recent = RPSession.objects.filter(
            status=RPSession.Status.COMPLETED,
            ended_at__gte=cutoff,
        ).order_by("-ended_at")[:20]

        lines = ["|w+rptracker Review|n", "=" * 60]

        active_count = sum(1 for s in _active_sessions.values() if s["status"] == "active")
        pending_count = sum(1 for s in _active_sessions.values() if s["status"] == "pending")
        lines.append(f"Live: |g{active_count} active|n, |y{pending_count} pending|n")
        lines.append("-" * 60)

        if flagged:
            lines.append("|rFlagged Sessions:|n")
            for s in flagged:
                flagged_at = s.flagged_at.strftime("%m-%d %H:%M") if s.flagged_at else "?"
                lines.append(
                    f"  #{s.pk} {s.character_name} — {s.flag_reason[:60]}"
                    f" (flagged {flagged_at} by {s.flagged_by_name})"
                )
            lines.append("")
        else:
            lines.append("|gNo flagged sessions.|n")
            lines.append("")

        lines.append("|wRecent Completed (past 7 days):|n")
        if recent.exists():
            for s in recent:
                lines.append(_format_session_row(s, show_char=True))
        else:
            lines.append("  (none)")

        lines.append("=" * 60)
        lines.append(
            "Use |w+rptracker/flag <id>=<reason>|n or "
            "|w+rptracker/unflag <id>|n to manage flags."
        )

        self.caller.msg("\n".join(lines))
