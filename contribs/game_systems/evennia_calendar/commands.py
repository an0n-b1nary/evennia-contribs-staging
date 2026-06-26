# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Calendar commands for evennia_calendar.

CmdCalendar (+calendar / +cal): event creation, viewing, editing, tagging,
  mutual exclusion, and EventCluster management.
CmdRsvp (+rsvp): single-event RSVP, cluster ranked-choice RSVP, host
  invite/ping, priority token management, waitlist, and confirmation flows.
"""

import contextlib
import datetime

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

try:
    from evennia_accessibility.utils import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        return False


# ---------------------------------------------------------------------------
# Staff-lock helper (shared by both commands)
# ---------------------------------------------------------------------------


def _is_staff(character):
    """Check if character has staff permissions via CALENDAR_STAFF_LOCK setting."""
    lock_expr = getattr(settings, "CALENDAR_STAFF_LOCK", "cmd:perm(Builder)")
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


def _event_web_path(pk):
    """Return a web URL for an event, gated on SITE_URL setting."""
    site_url = getattr(settings, "SITE_URL", "")
    return f"{site_url}/calendar/{pk}/"


# ---------------------------------------------------------------------------
# +calendar helpers
# ---------------------------------------------------------------------------


def _lookup_event(arg):
    """Resolve a CalendarEvent by PK string. Returns (event, err)."""
    from evennia_calendar.models import CalendarEvent

    arg = (arg or "").strip()
    if not arg.isdigit():
        return None, "Event ID must be a number (e.g. |w+calendar/view 5|n)."
    try:
        return CalendarEvent.objects.get(pk=int(arg)), None
    except CalendarEvent.DoesNotExist:
        return None, f"No event #{arg} found."


def _lookup_cluster(arg):
    """Resolve an EventCluster by PK string. Returns (cluster, err)."""
    from evennia_calendar.models import EventCluster

    arg = (arg or "").strip()
    if not arg.isdigit():
        return None, "Cluster ID must be a number."
    try:
        return EventCluster.objects.get(pk=int(arg)), None
    except EventCluster.DoesNotExist:
        return None, f"No cluster #{arg} found."


def _parse_datetime(raw):
    """
    Parse a datetime string into an aware UTC datetime, or return None.

    Accepted formats:
        YYYY-MM-DD HH:MM       (treated as UTC)
        YYYY-MM-DDTHH:MM       (treated as UTC)
        YYYY-MM-DD HH:MM+HH:MM (with timezone offset)
    """
    from django.utils import timezone

    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            naive = datetime.datetime.strptime(raw, fmt)
            return timezone.make_aware(naive, datetime.UTC)
        except ValueError:
            pass
    try:
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        return dt.astimezone(datetime.UTC)
    except ValueError:
        return None


def _is_event_owner(caller, event):
    """True if caller created the event or is staff."""
    return event.creator == caller or _is_staff(caller)


def _format_event_row(event):
    """Single-line summary for listing."""
    time_str = event.scheduled_time.strftime("%Y-%m-%d %H:%M")
    past_tag = " |x[past]|n" if event.is_past else ""
    staff_tag = " |y[staff]|n" if event.is_staff_event else ""
    cluster_tag = f" |m[{event.cluster.title}]|n" if event.is_clustered else ""
    return (
        f" |w#{event.pk:<4}|n {time_str} UTC  "
        f"{event.title[:40]:<40}"
        f"{past_tag}{staff_tag}{cluster_tag}"
    )


def _format_event_detail(event, sr_mode=False):
    """Multi-line event detail view."""
    if sr_mode:
        from evennia_calendar.models import RSVP

        staff_tag = " [staff lottery event]" if event.is_staff_event else ""
        tags = ", ".join(t.name for t in event.tags.all()) or "(none)"
        cap = event.participant_cap
        cap_str = f"{cap} max ({event.seats_remaining} remaining)" if cap else "Unlimited"
        web_url = _event_web_path(event.pk)
        lines = [
            f"Event #{event.pk}: {event.title}{staff_tag}" f" |lu{web_url}|lt[↗]|le",
            f"  Time: {event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC",
            f"  Emphasis: {event.get_emphasis_display()}",
            f"  Tags: {tags}",
            f"  Capacity: {cap_str}",
        ]
        if event.is_clustered:
            lines.append(
                f"  Cluster: {event.cluster.title} (#{event.cluster.pk})"
                " — use +rsvp/cluster to sign up"
            )
        if event.description:
            lines.append(f"  Description: {event.description}")
        rsvps = event.rsvps.exclude(status=RSVP.Status.RELEASED).order_by("created_at")
        if rsvps.exists():
            lines.append("  RSVPs:")
            for r in rsvps:
                lines.append(f"    {r.character_name} [{r.get_status_display()}]")
        if event.is_clustered:
            siblings = event.cluster.events.exclude(pk=event.pk).filter(is_cancelled=False)
            if siblings.exists():
                lines.append("  Other events in this cluster:")
                for s in siblings:
                    lines.append(
                        f"    #{s.pk} {s.title}"
                        f" — {s.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC"
                    )
        return "\n".join(lines)

    sep = "|b" + "=" * 70 + "|n"
    lines = [sep]
    staff_tag = " |y[STAFF EVENT — Lottery]|n" if event.is_staff_event else ""
    web_link = f" |lu{_event_web_path(event.pk)}|lt[↗]|le"
    lines.append(f" Event |w#{event.pk}|n — {event.title}{staff_tag}{web_link}")
    lines.append(sep)
    lines.append(f" Time    : {event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f" Emphasis: {event.get_emphasis_display()}")
    tags = ", ".join(t.name for t in event.tags.all())
    lines.append(f" Tags    : {tags or '(none)'}")
    cap = event.participant_cap
    if cap:
        remaining = event.seats_remaining
        lines.append(f" Cap     : {cap}  (seats remaining: {remaining})")
    else:
        lines.append(" Cap     : Unlimited")
    if event.is_clustered:
        lines.append(
            f" Cluster : |m{event.cluster.title}|n (#{event.cluster.pk}) — "
            f"use +rsvp/cluster to sign up"
        )
    if event.description:
        lines.append(sep)
        lines.append(event.description)
    # RSVP roster summary.
    from evennia_calendar.models import RSVP

    rsvps = event.rsvps.exclude(status=RSVP.Status.RELEASED).order_by("created_at")
    if rsvps.exists():
        lines.append(sep)
        lines.append(" RSVPs:")
        for r in rsvps:
            lines.append(f"   {r.character_name:<25} [{r.get_status_display()}]")
    lines.append(sep)
    # Sibling events if clustered.
    if event.is_clustered:
        siblings = event.cluster.events.exclude(pk=event.pk).filter(is_cancelled=False)
        if siblings.exists():
            lines.append(" Other events in this cluster:")
            for s in siblings:
                lines.append(
                    f"   |w#{s.pk}|n {s.title} — {s.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC"
                )
            lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EvEditor callbacks for event creation/editing
# ---------------------------------------------------------------------------


def _cal_load(caller):
    """Load existing description into editor (edit mode) or blank (create)."""
    ctx = getattr(caller.ndb, "_calendar_context", None)
    if not ctx:
        return ""
    if ctx.get("mode") == "edit":
        event_pk = ctx.get("event_pk")
        if event_pk:
            from evennia_calendar.models import CalendarEvent

            try:
                return CalendarEvent.objects.get(pk=event_pk).description
            except CalendarEvent.DoesNotExist:
                return ""
    return ctx.get("description", "")


def _cal_save(caller, buffer):
    """Save description buffer to context or directly to existing event."""
    ctx = getattr(caller.ndb, "_calendar_context", None)
    if not ctx:
        caller.msg("|rNo calendar editing context found.|n")
        return False
    if ctx.get("mode") == "edit":
        from evennia_calendar.models import CalendarEvent

        event_pk = ctx.get("event_pk")
        try:
            event = CalendarEvent.objects.get(pk=event_pk)
        except CalendarEvent.DoesNotExist:
            caller.msg("|rEvent no longer exists.|n")
            return False
        event.description = buffer.strip()
        event.save(update_fields=["description", "updated_at"])
        caller.msg(f"|gEvent #{event.pk} description updated.|n")
    else:
        ctx["description"] = buffer.strip()
    return True


def _cal_quit(caller):
    """Finalise create flow or clean up edit context."""
    ctx = getattr(caller.ndb, "_calendar_context", None)
    if not ctx:
        return
    if ctx.get("mode") == "create":
        _finalize_create(caller, ctx)
    caller.ndb._calendar_context = None


def _finalize_create(caller, ctx):
    """Create the CalendarEvent from the context dict."""
    from evennia_calendar.models import CalendarEvent
    from evennia_calendar.signals import event_created

    scheduled_time = ctx.get("scheduled_time")
    title = ctx.get("title", "Untitled Event")
    if not scheduled_time:
        caller.msg("|rCould not create event: no scheduled time.|n")
        return
    emphasis = ctx.get("emphasis", CalendarEvent.Emphasis.FREEFORM)
    event = CalendarEvent.create_event(
        creator=caller,
        title=title,
        scheduled_time=scheduled_time,
        description=ctx.get("description", ""),
        emphasis=emphasis,
        participant_cap=ctx.get("cap"),
        is_staff_event=ctx.get("is_staff_event", False),
        cluster=ctx.get("cluster"),
    )
    with contextlib.suppress(Exception):
        event_created.send(sender=CalendarEvent, event=event)
    caller.msg(
        f"|gEvent |w#{event.pk}|n |g'{event.title}'|n created for "
        f"|w{event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC|n.\n"
        f"Use |w+calendar/tag {event.pk}=<tag>|n to add thematic tags."
    )


# ---------------------------------------------------------------------------
# CmdCalendar
# ---------------------------------------------------------------------------


class CmdCalendar(MuxCommand):
    """
    View and manage the event calendar.

    Usage:
        +calendar                           - Upcoming events
        +calendar/past                      - Past events
        +calendar/view <id>                 - Event details and RSVP list
        +calendar/create <title>            - Schedule a new event (opens editor)
        +calendar/edit <id>                 - Edit your event description
        +calendar/cancel <id>               - Cancel an event
        +calendar/cap <id>=<number>         - Set or change participant cap
        +calendar/tag <id>=<tag>            - Add a thematic tag
        +calendar/untag <id>=<tag>          - Remove a thematic tag
        +calendar/tags                      - List all available thematic tags
        +calendar/exclusive <id>=<id>       - Declare mutual exclusion
        +calendar/staff <id>                - Toggle staff-event lottery mode

    Cluster management:
        +calendar/cluster <title>           - Create a new event cluster
        +calendar/cluster/add <eid>=<cid>   - Add event to cluster
        +calendar/cluster/remove <eid>      - Remove event from cluster
        +calendar/cluster/lock <cid>        - Lock cluster and arm the draw
        +calendar/cluster/view <cid>        - View cluster details

    Events have an emphasis category (Combat, Skill, Social, Freeform) set
    during creation, describing expected mechanical focus. Thematic tags
    (e.g. 'Arcane', 'Military') are optional and describe narrative theme.

    Staff events use a lottery for RSVP instead of first-come-first-serve.
    See +help +rsvp for the lottery and priority token system.

    A cluster groups related events (e.g. Battle/Stealth/Decoy for one plot
    night) and lets players rank their preferences. The lottery seats each
    player in their highest-ranked event with capacity.
    """

    key = "+calendar"
    aliases = ["+cal"]  # noqa: RUF012
    help_category = "Events"
    locks = "cmd:all()"

    def func(self):
        sw = self.switches

        # Cluster sub-commands (check compound switches before bare "cluster").
        # MuxCommand splits "+calendar/cluster/add" into switches=["cluster","add"],
        # so compound checks must test both parts individually.
        if "cluster" in sw and "add" in sw:
            self._cluster_add()
        elif "cluster" in sw and "remove" in sw:
            self._cluster_remove()
        elif "cluster" in sw and "lock" in sw:
            self._cluster_lock()
        elif "cluster" in sw and "view" in sw:
            self._cluster_view()
        elif "cluster" in sw:
            self._cluster_create()
        elif "past" in sw:
            self._list_past()
        elif "view" in sw:
            self._view()
        elif "create" in sw:
            self._create()
        elif "edit" in sw:
            self._edit()
        elif "cancel" in sw:
            self._cancel()
        elif "cap" in sw:
            self._cap()
        elif "tag" in sw and "untag" not in sw:
            self._tag()
        elif "untag" in sw:
            self._untag()
        elif "tags" in sw:
            self._tags()
        elif "exclusive" in sw:
            self._exclusive()
        elif "staff" in sw:
            self._toggle_staff()
        else:
            self._list_upcoming()

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def _list_upcoming(self):
        from django.utils import timezone

        from evennia_calendar.models import CalendarEvent

        events = CalendarEvent.objects.filter(
            is_cancelled=False,
            scheduled_time__gte=timezone.now(),
        ).order_by("scheduled_time")[:30]

        if not events:
            self.caller.msg("No upcoming events. Use |w+calendar/create <title>|n to schedule one.")
            return

        if uses_screenreader(self.caller):
            count = len(events)
            lines = [f"Upcoming Events: {count} event{'s' if count != 1 else ''}"]
            for ev in events:
                staff_tag = " [staff lottery]" if ev.is_staff_event else ""
                cluster_tag = f" [cluster: {ev.cluster.title}]" if ev.is_clustered else ""
                lines.append(
                    f"  #{ev.pk}: {ev.title}"
                    f" — {ev.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC,"
                    f" {ev.get_emphasis_display()}{staff_tag}{cluster_tag}"
                )
            self.caller.msg("\n".join(lines))
            return

        sep = "|b" + "-" * 70 + "|n"
        lines = [
            "|b" + "=" * 70 + "|n",
            "  Upcoming Events",
            sep,
        ]
        for ev in events:
            lines.append(_format_event_row(ev))
        lines.append(sep)
        lines.append("Use |w+calendar/view <id>|n for details and RSVP status.")
        self.caller.msg("\n".join(lines))

    def _list_past(self):
        from django.utils import timezone

        from evennia_calendar.models import CalendarEvent

        events = CalendarEvent.objects.filter(
            is_cancelled=False,
            scheduled_time__lt=timezone.now(),
        ).order_by("-scheduled_time")[:30]

        if not events:
            self.caller.msg("No past events found.")
            return

        if uses_screenreader(self.caller):
            count = len(events)
            lines = [f"Past Events (most recent first): {count} event{'s' if count != 1 else ''}"]
            for ev in events:
                staff_tag = " [staff lottery]" if ev.is_staff_event else ""
                cluster_tag = f" [cluster: {ev.cluster.title}]" if ev.is_clustered else ""
                lines.append(
                    f"  #{ev.pk}: {ev.title}"
                    f" — {ev.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC,"
                    f" {ev.get_emphasis_display()}{staff_tag}{cluster_tag}"
                )
            self.caller.msg("\n".join(lines))
            return

        sep = "|b" + "-" * 70 + "|n"
        lines = [
            "|b" + "=" * 70 + "|n",
            "  Past Events (most recent first)",
            sep,
        ]
        for ev in events:
            lines.append(_format_event_row(ev))
        lines.append(sep)
        self.caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    def _view(self):
        event, err = _lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        self.caller.msg(_format_event_detail(event, sr_mode=uses_screenreader(self.caller)))

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def _create(self):
        from evennia_calendar.models import CalendarEvent

        title = self.args.strip()
        if not title:
            self.caller.msg(
                "Usage: |w+calendar/create <title>|n\n"
                "After entering a title, you will be asked for time and emphasis, "
                "then an editor opens for the description."
            )
            return

        scheduled_time = None
        if "=" in title:
            parts = title.split("=", 1)
            title = parts[0].strip()
            scheduled_time = _parse_datetime(parts[1])

        if not scheduled_time:
            self.caller.msg(
                "Please include the scheduled time in the title arg:\n"
                "|w+calendar/create <title>=YYYY-MM-DD HH:MM|n\n"
                "Example: |w+calendar/create Founders Ball=2026-08-01 20:00|n\n\n"
                "Then the editor opens for the description. "
                "After saving, use |w+calendar/cap|n, |w+calendar/tag|n, etc."
            )
            return

        self.caller.ndb._calendar_context = {
            "mode": "create",
            "title": title,
            "scheduled_time": scheduled_time,
            "emphasis": CalendarEvent.Emphasis.FREEFORM,
            "cap": None,
            "is_staff_event": False,
            "cluster": None,
            "description": "",
        }
        EvEditor(
            self.caller,
            loadfunc=_cal_load,
            savefunc=_cal_save,
            quitfunc=_cal_quit,
            key="Event Description",
        )

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    def _edit(self):
        event, err = _lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only edit your own events.|n")
            return
        self.caller.ndb._calendar_context = {"mode": "edit", "event_pk": event.pk}
        EvEditor(
            self.caller,
            loadfunc=_cal_load,
            savefunc=_cal_save,
            quitfunc=lambda c: setattr(c.ndb, "_calendar_context", None),
            key="Event Description",
        )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def _cancel(self):
        event, err = _lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only cancel your own events.|n")
            return
        if event.is_cancelled:
            self.caller.msg("That event is already cancelled.")
            return
        event.cancel(cancelled_by=self.caller)
        from evennia_calendar.signals import event_cancelled

        with contextlib.suppress(Exception):
            event_cancelled.send(sender=event.__class__, event=event)
        self.caller.msg(f"|yEvent #{event.pk} '{event.title}' has been cancelled.|n")

    # ------------------------------------------------------------------
    # Cap
    # ------------------------------------------------------------------

    def _cap(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+calendar/cap <id>=<number>|n  (0 = unlimited)")
            return
        id_part, cap_part = self.args.split("=", 1)
        event, err = _lookup_event(id_part)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only change cap on your own events.|n")
            return
        cap_part = cap_part.strip()
        if cap_part == "0":
            event.participant_cap = None
        elif cap_part.isdigit():
            event.participant_cap = int(cap_part)
        else:
            self.caller.msg("Cap must be a number, or 0 for unlimited.")
            return
        event.save(update_fields=["participant_cap", "updated_at"])
        cap_str = str(event.participant_cap) if event.participant_cap else "Unlimited"
        self.caller.msg(f"Event #{event.pk} cap set to: {cap_str}")

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _tag(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+calendar/tag <id>=<tag name>|n")
            return
        id_part, tag_part = self.args.split("=", 1)
        event, err = _lookup_event(id_part)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only tag your own events.|n")
            return
        from evennia_calendar.models import EventTag

        tag_name = tag_part.strip()
        try:
            tag = EventTag.objects.get(name__iexact=tag_name)
        except EventTag.DoesNotExist:
            self.caller.msg(
                f"No tag '{tag_name}' exists. Use |w+calendar/tags|n to see available tags.\n"
                "(Staff can create tags via the Django admin.)"
            )
            return
        event.tags.add(tag)
        self.caller.msg(f"Tag '{tag.name}' added to event #{event.pk}.")

    def _untag(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+calendar/untag <id>=<tag name>|n")
            return
        id_part, tag_part = self.args.split("=", 1)
        event, err = _lookup_event(id_part)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only untag your own events.|n")
            return
        from evennia_calendar.models import EventTag

        tag_name = tag_part.strip()
        try:
            tag = EventTag.objects.get(name__iexact=tag_name)
        except EventTag.DoesNotExist:
            self.caller.msg(f"No tag '{tag_name}' found.")
            return
        event.tags.remove(tag)
        self.caller.msg(f"Tag '{tag.name}' removed from event #{event.pk}.")

    def _tags(self):
        from evennia_calendar.models import EventTag

        tags = list(EventTag.objects.all())
        if not tags:
            self.caller.msg("No thematic tags have been created yet.")
            return
        lines = [
            "|b" + "=" * 70 + "|n",
            "  Available Thematic Tags",
            "|b" + "-" * 70 + "|n",
        ]
        for tag in tags:
            desc = f" — {tag.description}" if tag.description else ""
            lines.append(f"  |w{tag.name}|n{desc}")
        lines.append("|b" + "-" * 70 + "|n")
        self.caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # Mutual exclusion
    # ------------------------------------------------------------------

    def _exclusive(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+calendar/exclusive <id>=<id>|n")
            return
        a_part, b_part = self.args.split("=", 1)
        event_a, err = _lookup_event(a_part)
        if err:
            self.caller.msg(err)
            return
        event_b, err = _lookup_event(b_part)
        if err:
            self.caller.msg(err)
            return
        if event_a.pk == event_b.pk:
            self.caller.msg("An event cannot be mutually exclusive with itself.")
            return
        if not (_is_event_owner(self.caller, event_a) or _is_event_owner(self.caller, event_b)):
            self.caller.msg("|rYou must be the creator of at least one of the two events.|n")
            return
        from evennia_calendar.models import EventExclusion

        if EventExclusion.are_exclusive(event_a, event_b):
            self.caller.msg(
                f"Events #{event_a.pk} and #{event_b.pk} are already mutually exclusive."
            )
            return
        EventExclusion.objects.create(
            event_a=event_a,
            event_b=event_b,
            created_by=self.caller,
            creator_name=self.caller.key,
        )
        self.caller.msg(
            f"|gEvents |w#{event_a.pk}|n and |w#{event_b.pk}|n are now mutually exclusive. "
            f"Players cannot RSVP for both.|n"
        )

    # ------------------------------------------------------------------
    # Staff toggle
    # ------------------------------------------------------------------

    def _toggle_staff(self):
        if not _is_staff(self.caller):
            self.caller.msg("|rOnly staff can toggle staff-event mode.|n")
            return
        event, err = _lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        event.is_staff_event = not event.is_staff_event
        event.save(update_fields=["is_staff_event", "updated_at"])
        mode = "|ystaff lottery|n" if event.is_staff_event else "|gnormal|n"
        self.caller.msg(f"Event #{event.pk} RSVP mode set to: {mode}")

    # ------------------------------------------------------------------
    # Cluster management
    # ------------------------------------------------------------------

    def _cluster_create(self):
        title = self.args.strip()
        if not title:
            self.caller.msg("Usage: |w+calendar/cluster <title>|n")
            return
        from evennia_calendar.models import EventCluster

        cluster = EventCluster.objects.create(
            title=title,
            creator=self.caller,
            creator_name=self.caller.key,
        )
        self.caller.msg(
            f"|gCluster |w#{cluster.pk}|n '{cluster.title}' created.\n"
            f"Add events: |w+calendar/cluster/add <event_id>={cluster.pk}|n\n"
            f"Lock when ready: |w+calendar/cluster/lock {cluster.pk}|n"
        )

    def _cluster_add(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+calendar/cluster/add <event_id>=<cluster_id>|n")
            return
        eid_part, cid_part = self.args.split("=", 1)
        event, err = _lookup_event(eid_part)
        if err:
            self.caller.msg(err)
            return
        cluster, err = _lookup_cluster(cid_part)
        if err:
            self.caller.msg(err)
            return
        if cluster.is_locked:
            self.caller.msg("|rThis cluster is locked. No changes to membership allowed.|n")
            return
        if not (_is_event_owner(self.caller, event) or _is_staff(self.caller)):
            self.caller.msg("|rYou must be the event creator or staff.|n")
            return
        event.cluster = cluster
        event.save(update_fields=["cluster", "updated_at"])
        self.caller.msg(
            f"Event #{event.pk} '{event.title}' added to cluster "
            f"#{cluster.pk} '{cluster.title}'."
        )

    def _cluster_remove(self):
        event, err = _lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        if not event.is_clustered:
            self.caller.msg("That event is not in a cluster.")
            return
        cluster = event.cluster
        if cluster.is_locked:
            self.caller.msg("|rThis cluster is locked. No changes to membership allowed.|n")
            return
        if not (_is_event_owner(self.caller, event) or _is_staff(self.caller)):
            self.caller.msg("|rYou must be the event creator or staff.|n")
            return
        event.cluster = None
        event.save(update_fields=["cluster", "updated_at"])
        self.caller.msg(f"Event #{event.pk} removed from cluster #{cluster.pk} '{cluster.title}'.")

    def _cluster_lock(self):
        cluster, err = _lookup_cluster(self.args)
        if err:
            self.caller.msg(err)
            return
        if not _is_staff(self.caller):
            self.caller.msg("|rOnly staff can lock a cluster.|n")
            return
        if cluster.is_locked:
            self.caller.msg("That cluster is already locked.")
            return
        events = list(cluster.events.all())
        if not events:
            self.caller.msg("|rCannot lock an empty cluster. Add events first.|n")
            return
        flags = set(e.is_staff_event for e in events)
        if len(flags) > 1:
            self.caller.msg(
                "|rAll events in the cluster must share the same staff-event "
                "setting before locking. Use +calendar/staff to adjust.|n"
            )
            return
        from django.utils import timezone

        now = timezone.now()
        for ev in events:
            if ev.lottery_draw_time and ev.lottery_draw_time < now:
                self.caller.msg(
                    f"|rEvent #{ev.pk} '{ev.title}' is within 72h of its "
                    f"scheduled time. Cannot lock a cluster this close to draw time.|n"
                )
                return
        cluster.is_locked = True
        cluster.save(update_fields=["is_locked", "updated_at"])
        self.caller.msg(
            f"|gCluster #{cluster.pk} '{cluster.title}' is now locked.|n\n"
            f"Players can RSVP via |w+rsvp/cluster {cluster.pk}=<event_ids>|n.\n"
            f"The lottery draw will run 72h before the earliest event "
            f"({cluster.draw_time.strftime('%Y-%m-%d %H:%M') if cluster.draw_time else 'N/A'} UTC)."
        )

    def _cluster_view(self):
        cluster, err = _lookup_cluster(self.args)
        if err:
            self.caller.msg(err)
            return
        from evennia_calendar.models import ClusterRSVP

        sep = "|b" + "=" * 70 + "|n"
        locked_tag = " |y[LOCKED]|n" if cluster.is_locked else " |g[open]|n"
        drawn_tag = " |m[DRAWN]|n" if cluster.has_run else ""
        lines = [
            sep,
            f" Cluster |w#{cluster.pk}|n — {cluster.title}{locked_tag}{drawn_tag}",
            f" Created by: {cluster.creator_name}",
            sep,
        ]
        if cluster.description:
            lines.append(cluster.description)
            lines.append(sep)
        events = cluster.events.filter(is_cancelled=False).order_by("scheduled_time")
        lines.append(" Member Events:")
        for ev in events:
            rsvp_pool = ev.rsvps.count()
            lines.append(
                f"   |w#{ev.pk}|n {ev.title} — "
                f"{ev.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC  "
                f"cap: {ev.participant_cap or 'open'}  "
                f"seated: {rsvp_pool}"
            )
        total_pending = ClusterRSVP.objects.filter(
            cluster=cluster, status=ClusterRSVP.Status.PENDING
        ).count()
        lines.append(sep)
        lines.append(f" Total ranked preferences submitted: {total_pending}")
        if not cluster.is_locked:
            lines.append(
                " RSVP opens after staff locks with " f"|w+calendar/cluster/lock {cluster.pk}|n"
            )
        else:
            lines.append(f" RSVP: |w+rsvp/cluster {cluster.pk}=<event_id1>,<event_id2>,...|n")
        if cluster.draw_time:
            lines.append(f" Draw time: {cluster.draw_time.strftime('%Y-%m-%d %H:%M')} UTC")
        lines.append(sep)
        self.caller.msg("\n".join(lines))


# ---------------------------------------------------------------------------
# +rsvp helpers
# ---------------------------------------------------------------------------


def _rsvp_lookup_event(arg):
    """Resolve a CalendarEvent by PK string. Returns (event, err)."""
    from evennia_calendar.models import CalendarEvent

    arg = (arg or "").strip()
    if not arg.isdigit():
        return None, "Event ID must be a number."
    try:
        return CalendarEvent.objects.get(pk=int(arg)), None
    except CalendarEvent.DoesNotExist:
        return None, f"No event #{arg} found."


def _rsvp_lookup_cluster(arg):
    """Resolve an EventCluster by PK string. Returns (cluster, err)."""
    from evennia_calendar.models import EventCluster

    arg = (arg or "").strip()
    if not arg.isdigit():
        return None, "Cluster ID must be a number."
    try:
        return EventCluster.objects.get(pk=int(arg)), None
    except EventCluster.DoesNotExist:
        return None, f"No cluster #{arg} found."


def _get_rsvp(event, character):
    """Return the RSVP for (event, character), or None."""
    from evennia_calendar.models import RSVP

    return RSVP.objects.filter(event=event, character=character).first()


def _has_conflicting_rsvp(event, character):
    """
    Check if character already has an active RSVP for a mutually exclusive event.

    Returns the conflicting CalendarEvent or None.
    """
    from evennia_calendar.models import RSVP, EventExclusion

    exclusions = EventExclusion.get_exclusions_for(event)
    for ex_event in exclusions:
        conflict = (
            RSVP.objects.filter(
                event=ex_event,
                character=character,
            )
            .exclude(status=RSVP.Status.RELEASED)
            .first()
        )
        if conflict:
            return ex_event
    return None


def _format_token_row(token):
    """Single-line summary for a priority token."""
    status = "|x[redeemed]|n" if token.is_redeemed else "|g[available]|n"
    scope_str = token.get_scope_display()
    source = ""
    if token.source_event:
        source = f" from event #{token.source_event_id} '{token.source_event.title}'"
    elif token.source_cluster:
        source = f" from cluster #{token.source_cluster_id} '{token.source_cluster.title}'"
    return f"  Token #{token.pk} [{scope_str}]{source}  {status}"


# ---------------------------------------------------------------------------
# CmdRsvp
# ---------------------------------------------------------------------------


class CmdRsvp(MuxCommand):
    """
    RSVP to a calendar event or cluster.

    Usage:
        +rsvp <event id>                     - RSVP to an event
        +rsvp/cancel <event id>              - Cancel your RSVP
        +rsvp/confirm <event id>             - Confirm invitation or lottery
                                               selection (24h deadline)
        +rsvp/list <event id>                - View all RSVPs and their status
        +rsvp/waitlist <event id>            - View the waitlist

    Host commands:
        +rsvp/invite <event id>=<character>  - Pre-invite a character (blocked
                                               for staff events)
        +rsvp/ping <event id>                - Offer spot to next waitlisted

    Priority tokens:
        +rsvp/token                          - View your priority tokens
        +rsvp/token/use <event id>           - Redeem a token for guaranteed
                                               entry to a staff event

    Cluster (ranked-choice) RSVP:
        +rsvp/cluster <cid>=<eid1>,<eid2>,...  - Submit ranked preferences
        +rsvp/cluster/view <cluster id>         - Your current preferences
        +rsvp/cluster/cancel <cluster id>       - Withdraw from cluster

    Three RSVP modes:
      Open (no cap):    RSVP and you're confirmed immediately.
      Capped:           First-come-first-serve up to the cap, then waitlisted.
                        The host may pre-invite characters (+rsvp/invite).
      Lottery (staff):  RSVP enters you into a random draw run 72h before
                        the event. Priority token holders are seated first.
                        Selected players confirm within 24h. Players not
                        selected receive a priority token.

    Clustered events use ranked-choice RSVP across all member events. Use
    +rsvp/cluster instead of +rsvp for events that belong to a cluster.
    """

    key = "+rsvp"
    aliases = []  # noqa: RUF012
    help_category = "Events"
    locks = "cmd:all()"

    def func(self):
        sw = self.switches

        if "cluster" in sw and "view" in sw:
            self._cluster_view()
        elif "cluster" in sw and "cancel" in sw:
            self._cluster_cancel()
        elif "cluster" in sw:
            self._cluster_rsvp()
        elif "cancel" in sw:
            self._cancel()
        elif "confirm" in sw:
            self._confirm()
        elif "list" in sw:
            self._list()
        elif "waitlist" in sw:
            self._waitlist()
        elif "invite" in sw:
            self._invite()
        elif "ping" in sw:
            self._ping()
        elif "token" in sw and "use" in sw:
            self._token_use()
        elif "token" in sw:
            self._token_list()
        else:
            self._rsvp()

    # ------------------------------------------------------------------
    # Single-event RSVP
    # ------------------------------------------------------------------

    def _rsvp(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return

        if event.is_cancelled:
            self.caller.msg("|rThat event has been cancelled.|n")
            return

        if event.is_past:
            self.caller.msg("|rThat event is in the past.|n")
            return

        if event.is_clustered:
            self.caller.msg(
                f"|yEvent #{event.pk} is part of cluster "
                f"|w#{event.cluster.pk}|n |y'{event.cluster.title}'|n.\n"
                f"Use |w+rsvp/cluster {event.cluster.pk}=<event_id1>,<event_id2>,...|n "
                f"to submit your ranked preferences.\n"
                f"View the cluster: |w+calendar/cluster/view {event.cluster.pk}|n"
            )
            return

        existing = _get_rsvp(event, self.caller)
        if existing and existing.status != existing.Status.RELEASED:
            self.caller.msg(
                f"You already have an RSVP for event #{event.pk} "
                f"(status: {existing.get_status_display()})."
            )
            return

        conflict = _has_conflicting_rsvp(event, self.caller)
        if conflict:
            self.caller.msg(
                f"|rThis event is mutually exclusive with |w'{conflict.title}'|n "
                f"|r(#{conflict.pk}), which you are already signed up for. "
                f"Cancel that RSVP first with |w+rsvp/cancel {conflict.pk}|n.|n"
            )
            return

        from evennia_calendar.models import RSVP
        from evennia_calendar.signals import rsvp_status_changed

        if event.is_staff_event:
            rsvp = RSVP.objects.create(
                event=event,
                character=self.caller,
                character_name=self.caller.key,
                status=RSVP.Status.LOTTERY_ENTERED,
            )
            self.caller.msg(
                f"|gYou have entered the lottery for |w'{event.title}'|n "
                f"(#{event.pk}).\n"
                f"The draw runs 72h before the event "
                f"({event.lottery_draw_time.strftime('%Y-%m-%d %H:%M') if event.lottery_draw_time else 'N/A'} UTC).\n"
                f"Selected players must confirm within 24h."
            )
        elif event.participant_cap is not None and event.seats_remaining == 0:
            from django.db.models import Max

            max_pos = (
                event.rsvps.filter(status=RSVP.Status.WAITLISTED)
                .aggregate(m=Max("waitlist_position"))
                .get("m")
            ) or 0
            rsvp = RSVP.objects.create(
                event=event,
                character=self.caller,
                character_name=self.caller.key,
                status=RSVP.Status.WAITLISTED,
                waitlist_position=max_pos + 1,
            )
            self.caller.msg(
                f"|yEvent '{event.title}' is at capacity. "
                f"You have been waitlisted at position {rsvp.waitlist_position}.|n"
            )
        else:
            rsvp = RSVP.objects.create(
                event=event,
                character=self.caller,
                character_name=self.caller.key,
                status=RSVP.Status.CONFIRMED,
            )
            self.caller.msg(
                f"|gYou are confirmed for |w'{event.title}'|n "
                f"({event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC).|n"
            )

        with contextlib.suppress(Exception):
            rsvp_status_changed.send(
                sender=rsvp.__class__,
                rsvp=rsvp,
                old_status=None,
                new_status=rsvp.status,
            )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def _cancel(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        rsvp = _get_rsvp(event, self.caller)
        if not rsvp or rsvp.status == rsvp.Status.RELEASED:
            self.caller.msg("You don't have an active RSVP for that event.")
            return
        old_status = rsvp.status
        rsvp.release()
        if (
            old_status == rsvp.Status.CONFIRMED
            and event.participant_cap
            and not event.is_staff_event
        ):
            from evennia_calendar.scheduler import promote_waitlist

            promote_waitlist(event, count=1)
        self.caller.msg(f"|yYour RSVP for '{event.title}' has been cancelled.|n")

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def _confirm(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        rsvp = _get_rsvp(event, self.caller)
        if not rsvp:
            self.caller.msg("You don't have an RSVP for that event.")
            return
        if rsvp.status not in (rsvp.Status.LOTTERY_SELECTED, rsvp.Status.INVITED):
            self.caller.msg(
                f"Your RSVP status is '{rsvp.get_status_display()}'. "
                "Only LOTTERY_SELECTED or INVITED RSVPs need confirmation."
            )
            return
        rsvp.confirm()
        self.caller.msg(
            f"|gYou are confirmed for |w'{event.title}'|n "
            f"({event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC).|n"
        )

    # ------------------------------------------------------------------
    # List / waitlist
    # ------------------------------------------------------------------

    def _list(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        from evennia_calendar.models import RSVP

        rsvps = event.rsvps.exclude(status=RSVP.Status.RELEASED).order_by("status", "created_at")
        sep = "|b" + "-" * 60 + "|n"
        lines = [
            "|b" + "=" * 60 + "|n",
            f" RSVPs for |w'{event.title}'|n (#{event.pk})",
            sep,
        ]
        if not rsvps:
            lines.append("  (no RSVPs yet)")
        for r in rsvps:
            lines.append(f"  {r.character_name:<25} [{r.get_status_display()}]")
        lines.append(sep)
        self.caller.msg("\n".join(lines))

    def _waitlist(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        from evennia_calendar.models import RSVP

        waitlisted = event.rsvps.filter(status=RSVP.Status.WAITLISTED).order_by("waitlist_position")
        if not waitlisted:
            self.caller.msg(f"No one is waitlisted for '{event.title}'.")
            return
        lines = [
            "|b" + "=" * 60 + "|n",
            f" Waitlist for |w'{event.title}'|n",
            "|b" + "-" * 60 + "|n",
        ]
        for r in waitlisted:
            lines.append(f"  #{r.waitlist_position:<3} {r.character_name}")
        lines.append("|b" + "-" * 60 + "|n")
        self.caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # Host: invite
    # ------------------------------------------------------------------

    def _invite(self):
        if "=" not in self.args:
            self.caller.msg("Usage: |w+rsvp/invite <event id>=<character>|n")
            return
        id_part, char_part = self.args.split("=", 1)
        event, err = _rsvp_lookup_event(id_part)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only invite players to your own events.|n")
            return
        # Anti-favoritism: staff accounts cannot pre-invite for staff events.
        if event.is_staff_event and _is_staff(self.caller):
            self.caller.msg(
                "|rStaff characters cannot pre-invite players to staff events. "
                "This restriction exists to prevent favoritism — the lottery "
                "ensures fair access for everyone.|n"
            )
            return
        if event.is_clustered and event.cluster and event.is_staff_event and _is_staff(self.caller):
            self.caller.msg("|rPre-inviting is blocked for staff events in a cluster.|n")
            return

        from evennia.utils.search import search_object

        results = search_object(char_part.strip(), typeclass="typeclasses.characters.Character")
        if not results:
            self.caller.msg(f"No character '{char_part.strip()}' found.")
            return
        target = results[0]

        if event.participant_cap is not None:
            from evennia_calendar.models import RSVP

            confirmed = event.rsvps.filter(status=RSVP.Status.CONFIRMED).count()
            invited = event.rsvps.filter(status=RSVP.Status.INVITED).count()
            if confirmed + invited >= event.participant_cap:
                self.caller.msg(
                    f"|rEvent #{event.pk} is at capacity "
                    f"({event.participant_cap} spots). Cannot invite more.|n"
                )
                return

        existing = _get_rsvp(event, target)
        if existing and existing.status not in (
            existing.Status.RELEASED,
            existing.Status.WAITLISTED,
        ):
            self.caller.msg(
                f"{target.key} already has an active RSVP for this event "
                f"(status: {existing.get_status_display()})."
            )
            return

        from evennia_calendar.models import RSVP
        from evennia_calendar.signals import rsvp_status_changed

        if existing:
            old_status = existing.status
            existing.status = RSVP.Status.INVITED
            existing.waitlist_position = None
            existing.save(update_fields=["status", "waitlist_position", "updated_at"])
            rsvp = existing
        else:
            rsvp = RSVP.objects.create(
                event=event,
                character=target,
                character_name=target.key,
                status=RSVP.Status.INVITED,
            )
            old_status = None

        with contextlib.suppress(Exception):
            rsvp_status_changed.send(
                sender=rsvp.__class__,
                rsvp=rsvp,
                old_status=old_status,
                new_status=RSVP.Status.INVITED,
            )

        self.caller.msg(f"|g{target.key} has been invited to '{event.title}'.|n")
        if target.has_account:
            target.msg(
                f"|y{self.caller.key} has invited you to |w'{event.title}'|n "
                f"({event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC).\n"
                f"Confirm with |w+rsvp/confirm {event.pk}|n "
                f"(deadline: {event.confirmation_deadline.strftime('%Y-%m-%d %H:%M')} UTC).|n"
            )

    # ------------------------------------------------------------------
    # Host: ping
    # ------------------------------------------------------------------

    def _ping(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        if not _is_event_owner(self.caller, event):
            self.caller.msg("|rYou can only ping waitlist on your own events.|n")
            return
        from evennia_calendar.models import RSVP
        from evennia_calendar.signals import waitlist_promoted

        next_up = (
            event.rsvps.filter(status=RSVP.Status.WAITLISTED).order_by("waitlist_position").first()
        )
        if not next_up:
            self.caller.msg(f"No one is waitlisted for '{event.title}'.")
            return
        next_up.status = RSVP.Status.INVITED
        next_up.waitlist_position = None
        next_up.save(update_fields=["status", "waitlist_position", "updated_at"])
        with contextlib.suppress(Exception):
            waitlist_promoted.send(sender=next_up.__class__, event=event, rsvp=next_up)
        self.caller.msg(
            f"|g{next_up.character_name} has been offered the next spot "
            f"for '{event.title}'. They must confirm with +rsvp/confirm {event.pk}.|n"
        )
        if next_up.character and next_up.character.has_account:
            next_up.character.msg(
                f"|yA spot has opened for |w'{event.title}'|n! "
                f"Use |w+rsvp/confirm {event.pk}|n to accept "
                f"(deadline: {event.confirmation_deadline.strftime('%Y-%m-%d %H:%M')} UTC).|n"
            )

    # ------------------------------------------------------------------
    # Priority tokens
    # ------------------------------------------------------------------

    def _token_list(self):
        from evennia_calendar.models import PriorityToken

        tokens = PriorityToken.objects.filter(character=self.caller).order_by("created_at")
        if not tokens:
            self.caller.msg("You have no priority tokens.")
            return
        sep = "|b" + "-" * 70 + "|n"
        lines = [
            "|b" + "=" * 70 + "|n",
            "  Your Priority Tokens",
            sep,
        ]
        for token in tokens:
            lines.append(_format_token_row(token))
        available = tokens.filter(redeemed_at__isnull=True).count()
        lines.append(sep)
        lines.append(f"  Available: {available}  Total: {tokens.count()}")
        lines.append(
            "  Redeem an EVENT token: |w+rsvp/token/use <event id>|n\n"
            "  CLUSTER_RANK1 tokens are redeemed automatically at draw time."
        )
        lines.append(sep)
        self.caller.msg("\n".join(lines))

    def _token_use(self):
        event, err = _rsvp_lookup_event(self.args)
        if err:
            self.caller.msg(err)
            return
        if not event.is_staff_event:
            self.caller.msg("|rPriority tokens only apply to staff events (lottery mode).|n")
            return
        if event.is_cancelled:
            self.caller.msg("|rThat event has been cancelled.|n")
            return
        if event.lottery_drawn_at:
            self.caller.msg("|rThe lottery for that event has already been drawn.|n")
            return
        from evennia_calendar.models import PriorityToken

        token = PriorityToken.objects.filter(
            character=self.caller,
            scope=PriorityToken.Scope.EVENT,
            redeemed_at__isnull=True,
        ).first()
        if not token:
            self.caller.msg(
                "You don't have an available EVENT priority token.\n"
                "Check your tokens with |w+rsvp/token|n."
            )
            return
        token.redeemed_event = event
        token.save(update_fields=["redeemed_event"])

        from evennia_calendar.models import RSVP

        rsvp, _ = RSVP.objects.get_or_create(
            event=event,
            character=self.caller,
            defaults={
                "character_name": self.caller.key,
                "status": RSVP.Status.LOTTERY_ENTERED,
            },
        )
        if rsvp.status == RSVP.Status.RELEASED:
            rsvp.status = RSVP.Status.LOTTERY_ENTERED
            rsvp.save(update_fields=["status", "updated_at"])

        self.caller.msg(
            f"|gPriority token #{token.pk} earmarked for |w'{event.title}'|n.\n"
            f"You will be seated before the random draw runs "
            f"({event.lottery_draw_time.strftime('%Y-%m-%d %H:%M') if event.lottery_draw_time else 'N/A'} UTC).|n"
        )

    # ------------------------------------------------------------------
    # Cluster RSVP
    # ------------------------------------------------------------------

    def _cluster_rsvp(self):
        """
        +rsvp/cluster <cluster_id>=<event_id1>,<event_id2>,...

        Submits or replaces the player's ranked preference list for a cluster.
        """
        if "=" not in self.args:
            self.caller.msg(
                "Usage: |w+rsvp/cluster <cluster_id>=<event_id1>,<event_id2>,...|n\n"
                "List event IDs in order from most to least preferred.\n"
                "Events you omit are treated as 'I'd rather sit this one out.'"
            )
            return
        cid_part, pref_part = self.args.split("=", 1)
        cluster, err = _rsvp_lookup_cluster(cid_part)
        if err:
            self.caller.msg(err)
            return
        if not cluster.is_locked:
            self.caller.msg(
                "|rThis cluster hasn't been locked yet. "
                "RSVPs open after staff lock it with "
                f"+calendar/cluster/lock {cluster.pk}|n"
            )
            return
        if cluster.has_run:
            self.caller.msg("|rThe draw for this cluster has already run.|n")
            return

        raw_ids = [x.strip() for x in pref_part.split(",") if x.strip()]
        if not raw_ids:
            self.caller.msg("Please list at least one event ID.")
            return
        from evennia_calendar.models import CalendarEvent, ClusterRSVP, ClusterRSVPPreference

        events = []
        for raw in raw_ids:
            if not raw.isdigit():
                self.caller.msg(f"'{raw}' is not a valid event ID.")
                return
            try:
                ev = CalendarEvent.objects.get(pk=int(raw), cluster=cluster)
            except CalendarEvent.DoesNotExist:
                self.caller.msg(f"Event #{raw} either doesn't exist or is not in this cluster.")
                return
            if ev.is_cancelled:
                self.caller.msg(f"Event #{ev.pk} '{ev.title}' has been cancelled.")
                return
            if ev in events:
                self.caller.msg(f"Event #{ev.pk} appears more than once in your list.")
                return
            events.append(ev)

        crsvp, created = ClusterRSVP.objects.get_or_create(
            cluster=cluster,
            character=self.caller,
            defaults={"character_name": self.caller.key},
        )
        if not created and crsvp.status != ClusterRSVP.Status.PENDING:
            self.caller.msg(
                f"|rYour cluster RSVP status is '{crsvp.get_status_display()}' "
                f"and can no longer be changed.|n"
            )
            return

        crsvp.preferences.all().delete()
        for rank, ev in enumerate(events, start=1):
            ClusterRSVPPreference.objects.create(
                cluster_rsvp=crsvp,
                event=ev,
                rank=rank,
            )

        pref_summary = ", ".join(f"|w#{ev.pk}|n {ev.title}" for ev in events)
        self.caller.msg(
            f"|gRanked preferences for cluster |w'{cluster.title}'|n submitted:\n"
            f"{pref_summary}\n"
            f"(Rank 1 = most preferred. The draw seats you in the highest-ranked "
            f"event with capacity.)\n"
            f"View: |w+rsvp/cluster/view {cluster.pk}|n  "
            f"Cancel: |w+rsvp/cluster/cancel {cluster.pk}|n"
        )

    def _cluster_view(self):
        """Show the player's own ranked preferences and draw status."""
        cluster, err = _rsvp_lookup_cluster(self.args)
        if err:
            self.caller.msg(err)
            return
        from evennia_calendar.models import ClusterRSVP

        try:
            crsvp = ClusterRSVP.objects.get(cluster=cluster, character=self.caller)
        except ClusterRSVP.DoesNotExist:
            self.caller.msg(
                f"You don't have a cluster RSVP for '{cluster.title}'.\n"
                f"Submit preferences with |w+rsvp/cluster {cluster.pk}=<event_ids>|n."
            )
            return

        sep = "|b" + "-" * 60 + "|n"
        lines = [
            "|b" + "=" * 60 + "|n",
            f" Your RSVP for cluster |w'{cluster.title}'|n",
            f" Status: {crsvp.get_status_display()}",
            sep,
        ]
        prefs = crsvp.get_ordered_preferences()
        if prefs:
            lines.append(" Your ranked preferences:")
            for p in prefs:
                lines.append(
                    f"   #{p.rank}: |w{p.event.title}|n "
                    f"(#{p.event_id}, "
                    f"{p.event.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC)"
                )
        else:
            lines.append("  (no preferences set yet)")
        lines.append(sep)
        concrete = crsvp.concrete_rsvps.first()
        if concrete:
            lines.append(
                f" Assigned event: |w'{concrete.event.title}'|n "
                f"[{concrete.get_status_display()}]"
            )
        lines.append(sep)
        self.caller.msg("\n".join(lines))

    def _cluster_cancel(self):
        """Withdraw from cluster before draw."""
        cluster, err = _rsvp_lookup_cluster(self.args)
        if err:
            self.caller.msg(err)
            return
        from evennia_calendar.models import ClusterRSVP

        try:
            crsvp = ClusterRSVP.objects.get(cluster=cluster, character=self.caller)
        except ClusterRSVP.DoesNotExist:
            self.caller.msg(f"You don't have a cluster RSVP for '{cluster.title}'.")
            return
        if crsvp.status != ClusterRSVP.Status.PENDING:
            self.caller.msg(
                f"|rCannot cancel: your cluster RSVP status is "
                f"'{crsvp.get_status_display()}'.|n"
            )
            return
        if cluster.has_run:
            self.caller.msg("|rThe draw has already run for this cluster.|n")
            return
        crsvp.preferences.all().delete()
        crsvp.delete()
        self.caller.msg(f"|yYou have withdrawn from cluster '{cluster.title}'.|n")
