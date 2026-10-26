# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Plot thread and plot arc management commands for evennia_plots.

Commands for creating, linking, and following plots and arcs.
Includes a staff nudge command for connecting players to storylines.

Commands:
    CmdPlot  (+plot) — create, manage, view, and follow plots
    CmdThread (+thread) — manage questions, problems and leads inside plots
    CmdArc   (+arc)  — manage plot arcs (PLOTS_STAFF_LOCK)
    CmdHook  (+hook) — nudge a player toward a plot (PLOTS_STAFF_LOCK)

**Accessibility shim:** If the ``evennia-accessibility`` package is installed,
``uses_screenreader(caller)`` is imported from it; otherwise it is a no-op
that always returns False.

**Web URL shim:** ``_plot_web_path(pk)`` constructs ``/plots/<pk>/`` relative
URLs. Set ``SITE_URL = "https://yourdomain.com"`` in your settings to emit
absolute URLs for MXP telnet clients.

**Optional dependencies (imported lazily):**
- ``evennia_scenes`` — scene lookup in ``+plot/scene``
- ``evennia_calendar`` — event lookup in ``+plot/event``
- ``evennia_boards`` — board/post lookup in ``+plot/post``
- ``evennia_jobs`` — job ticket creation in ``+plot/request-conclude``
- ``evennia_xp`` — XP award in ``+arc/award``
"""

import difflib
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_plots.command_syntax import split_comment
from evennia_plots.models import PlotArc
from evennia_plots.permissions import can_manage_arc, is_plot_staff
from evennia_plots.signals import arc_currency_changed, arc_type_changed

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(caller):
        return False


try:
    from evennia_boards.commands import _lookup_board, _lookup_post
except ImportError:
    _lookup_board = None
    _lookup_post = None

# ---------------------------------------------------------------------------
# Web URL helper
# ---------------------------------------------------------------------------

_MAX_PLOT_FOLLOWS = 20


def _plot_web_path(pk):
    """Return a web path for a plot. Absolute if SITE_URL is set."""
    from django.conf import settings

    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}/plots/{pk}/"


# ---------------------------------------------------------------------------
# EvEditor callbacks for PlotUpdate block creation / editing
# ---------------------------------------------------------------------------


def _update_load(caller):
    """EvEditor load: return existing block content (edit mode) or empty (new)."""
    ctx = caller.attributes.get("plots_update_editor")
    if not ctx:
        return ""
    if ctx.get("mode") == "edit":
        from evennia_plots.models import PlotUpdate

        try:
            block = PlotUpdate.objects.get(pk=ctx["block_pk"])
            return block.content
        except PlotUpdate.DoesNotExist:
            caller.msg("|rError: that update block no longer exists.|n")
            return ""
    return ""


def _update_save(caller, buffer):
    """EvEditor save: create a new block or update an existing one."""
    ctx = caller.attributes.get("plots_update_editor")
    if not ctx:
        caller.msg("|rError: no editing context found.|n")
        return False

    content = buffer.strip()
    if not content:
        caller.msg("Nothing to save — buffer is empty.")
        return False

    if ctx.get("mode") == "edit":
        from evennia_plots.models import PlotUpdate

        try:
            block = PlotUpdate.objects.get(pk=ctx["block_pk"])
        except PlotUpdate.DoesNotExist:
            caller.msg("|rError: that update block no longer exists.|n")
            return False
        if content == block.content.strip():
            caller.msg("No changes detected.")
            return True
        block.content = content
        block.edited_at = timezone.now()
        block.save(update_fields=["content", "edited_at"])
        caller.msg(f"|gUpdate block {block.block_number} saved.|n")
    else:
        from django.apps import apps

        from evennia_plots.models import PlotParticipant, PlotUpdate

        parent_model = apps.get_model("evennia_plots", ctx["parent_model"])
        try:
            parent = parent_model.objects.get(pk=ctx["parent_pk"])
        except parent_model.DoesNotExist:
            caller.msg("|rError: the plot or arc no longer exists.|n")
            return False
        update_type = ctx.get("update_type", PlotUpdate.UpdateType.IC)
        block = PlotUpdate.create_update(
            parent=parent,
            author=caller,
            content=content,
            update_type=update_type,
        )
        label = "OOC note" if update_type == PlotUpdate.UpdateType.OOC else "IC update"
        caller.msg(f"|gAdded {label} (block {block.block_number}).|n")
        # Auto-register poster as participant on thread updates
        if hasattr(parent, "plot_number"):
            PlotParticipant.objects.get_or_create(
                thread=parent,
                character=caller,
                defaults={"character_name": caller.key},
            )
    return True


def _update_quit(caller):
    """EvEditor quit: clean up context."""
    caller.attributes.remove("plots_update_editor")
    caller.msg("Editor closed.")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_thread(arg, caller):
    """
    Resolve a PlotThread from a '#N' id or partial name match.

    Visibility rules:
    - Staff (PLOTS_STAFF_LOCK) see threads of any status.
    - Players see: active public threads + threads they created or are invited to.

    Returns:
        (PlotThread, None) on unambiguous match.
        (None, error_str) on failure or ambiguity.
    """
    from evennia_plots.models import PlotThread

    arg = arg.strip()
    staff = is_plot_staff(caller)

    if arg.startswith("#"):
        num_str = arg[1:]
        if not num_str.isdigit():
            return None, f"'{arg}' is not a valid plot ID. Use #N (e.g. #5)."
        try:
            t = PlotThread.objects.get(plot_number=int(num_str))
        except PlotThread.DoesNotExist:
            return None, f"No plot #{num_str} found."
        if not staff and not t.can_view(caller):
            return None, f"No plot #{num_str} found."
        return t, None

    # Partial name match — build candidate pool
    qs = (
        PlotThread.objects.all()
        if staff
        else PlotThread.objects.filter(
            status=PlotThread.Status.ACTIVE, privacy__in=["public", "invite_only"]
        )
    )
    threads = list(qs)

    # For non-staff, also include plots the caller owns or is invited to
    if not staff:
        extra = (
            PlotThread.objects.filter(
                status__in=[PlotThread.Status.PROPOSED, PlotThread.Status.ACTIVE]
            )
            .filter(Q(owners__character=caller) | Q(invited_characters=caller))
            .exclude(id__in=[t.id for t in threads])
            .distinct()
        )
        threads.extend(extra)

    name_map = {t.name: t for t in threads}
    for name, thread in name_map.items():
        if name.lower() == arg.lower():
            return thread, None
    matches = [t for name, t in name_map.items() if arg.lower() in name.lower()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(f"#{t.plot_number} {t.name}" for t in matches[:5])
        return None, f"Multiple plots match '{arg}': {names}. Use #N to be specific."
    close = difflib.get_close_matches(arg, name_map.keys(), n=3, cutoff=0.5)
    if close:
        suggestions = ", ".join(f"#{name_map[n].plot_number} {n}" for n in close)
        return None, f"No plot '{arg}' found. Did you mean: {suggestions}?"
    return None, f"No plot matching '{arg}' found."


def _resolve_arc(arg, caller):
    """
    Resolve a PlotArc from a '#N' id or partial name match.

    Returns:
        (PlotArc, None) on success.
        (None, error_str) on failure.
    """
    from evennia_plots.models import PlotArc

    arg = arg.strip()

    if arg.startswith("#"):
        num_str = arg[1:]
        if not num_str.isdigit():
            return None, f"'{arg}' is not a valid arc ID. Use #N (e.g. #2)."
        try:
            return PlotArc.objects.get(arc_number=int(num_str)), None
        except PlotArc.DoesNotExist:
            return None, f"No plot arc #{num_str} found."

    try:
        return PlotArc.objects.get(name__iexact=arg), None
    except PlotArc.DoesNotExist:
        pass
    except PlotArc.MultipleObjectsReturned:
        return None, f"Multiple arcs match '{arg}'. Use #N to be specific."

    matches = list(PlotArc.objects.filter(name__icontains=arg))
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(f"#{a.arc_number} {a.name}" for a in matches[:5])
        return None, f"Multiple arcs match '{arg}': {names}. Use #N to be specific."
    return None, f"No plot arc matching '{arg}' found."


def _owner_names(plot):
    names = [o.character_name for o in plot.owners.all() if o.character_name]
    return ", ".join(names) or "none (staff manage it)"


def _format_thread_header(thread, caller):
    """Return a formatted header line for a plot."""
    tags = " ".join(f"|c[{t.name}]|n" for t in thread.tags.all()) or "|x(no tags)|n"
    status_color = {
        "proposed": "|y",
        "active": "|g",
        "concluded": "|b",
        "archived": "|x",
    }.get(thread.status, "")
    arc_str = f" | Arc: {thread.arc}" if thread.arc else ""
    web_link = f" |lu{_plot_web_path(thread.pk)}|lt[↗]|le"
    led = " |y[Owner-led]|n" if thread.is_owner_led else ""
    return (
        f"|w== Plot #{thread.plot_number}: {thread.name} ==|n{web_link}{led}\n"
        f"Tags: {tags}\n"
        f"Status: {status_color}{thread.get_status_display()}|n"
        f" | Privacy: {thread.get_privacy_display()}"
        f" | Owners: {_owner_names(thread)}{arc_str}"
    )


def _thread_counts(plot, caller):
    """List suffix: open threads, Owner-led, and (for managers) waiting requests."""
    from evennia_plots.models import StoryThread

    counts = []
    open_count = plot.story_threads.filter(status=StoryThread.Status.OPEN).count()
    if open_count:
        counts.append(f"{open_count} open thread{'s' if open_count != 1 else ''}")
    if plot.is_owner_led:
        counts.append("Owner-led")
    if plot.can_manage(caller):
        waiting = plot.story_threads.filter(status=StoryThread.Status.REQUESTED).count()
        if waiting:
            counts.append(f"{waiting} request{'s' if waiting != 1 else ''} waiting")
    return "".join(f", {c}" for c in counts)


def _owner_characters(plot, skip=None):
    """The plot's owner characters, optionally leaving one out."""
    return [
        o.character
        for o in plot.owners.select_related("character")
        if o.character is not None and (skip is None or o.character.pk != skip.pk)
    ]


def _loose_end_note(plot):
    """After conclude/archive: name the threads left as loose ends, if any."""
    from evennia_plots.models import StoryThread

    loose = list(plot.story_threads.filter(status=StoryThread.Status.LOOSE_END))
    if not loose:
        return ""
    refs = ", ".join(t.ref for t in loose)
    return (
        f"\nLoose ends: {refs}. Leaving threads open is fine. To pick one up in a sequel, "
        f"use |w+thread/carry <#N.T>=<#sequel>|n."
    )


def _seal_note(thread):
    """After resolve/drop: say what happened to a sealed answer."""
    if not thread.has_sealed_answer:
        return ""
    if thread.sealed_answer_revealed:
        return "\nThe planned answer is now revealed."
    return (
        f"\nThe sealed answer stays sealed. Reveal it later with |w+thread/reveal {thread.ref}|n."
    )


def _can_edit_thread(thread, caller):
    """Return True if caller is one of the plot's owners, or staff."""
    return thread.can_manage(caller)


def _resolve_story_thread(arg, caller):
    """Resolve a thread from ``#N.T`` (plot number, thread number).

    Returns:
        (StoryThread, None) on success, (None, error_str) otherwise.
    """
    from evennia_plots.models import StoryThread
    from evennia_plots.threads import visible_threads

    ref = arg.strip().lstrip("#")
    plot_part, dot, thread_part = ref.partition(".")
    if not dot or not plot_part.isdigit() or not thread_part.isdigit():
        return None, f"'{arg.strip()}' is not a thread reference. Use #<plot>.<thread>, e.g. #12.3."
    plot, err = _resolve_thread(f"#{plot_part}", caller)
    if err:
        return None, err
    thread = StoryThread.objects.filter(plot=plot, number=int(thread_part)).first()
    if thread is None or thread not in visible_threads(plot, caller):
        return None, f"No thread #{plot.plot_number}.{thread_part} found."
    return thread, None


def _thread_line(thread, screenreader=False):
    """One line describing a thread for +plot <#N>."""
    from evennia_plots.models import StoryThread

    status = thread.status
    interests = list(thread.interests.all())
    leads = [i.character_name for i in interests if i.is_lead]
    others = sum(1 for i in interests if not i.is_lead)
    extras = []
    if leads:
        extras.append(f"led by {', '.join(leads)}")
    if others:
        extras.append(f"{others} interested")
    if status == StoryThread.Status.REQUESTED:
        extras.append(f"requested by {thread.created_by_name}")
    if status == StoryThread.Status.DECLINED and thread.decline_reason:
        extras.append(f"declined: {thread.decline_reason}")
    if status == StoryThread.Status.CARRIED and thread.carried_to_id:
        extras.append(f"carried to {thread.carried_to.ref}")
    tail = f" ({'; '.join(extras)})" if extras else ""
    if screenreader:
        held = ", held" if thread.is_held else ""
        return f"  {thread.ref} {thread.title} - {thread.get_status_display()}{held}{tail}"
    held = " |y[Held]|n" if thread.is_held else ""
    label = "" if status == StoryThread.Status.OPEN else f" |x[{thread.get_status_display()}]|n"
    return f"  |w{thread.ref}|n {thread.title}{held}{label}{tail}"


def _thread_section(plot, caller, screenreader=False):
    """Lines for the Threads section of +plot <#N>; empty when there are none.

    Open threads come first, held ones leading, then requests; finished
    threads follow with their resolutions. A sealed answer appears only once
    it has been revealed.
    """
    from evennia_plots.models import StoryThread
    from evennia_plots.threads import visible_threads

    threads = visible_threads(plot, caller)
    if not threads:
        return []
    live = (StoryThread.Status.OPEN, StoryThread.Status.REQUESTED)
    current = sorted(
        (t for t in threads if t.status in live),
        key=lambda t: (t.status != StoryThread.Status.OPEN, not t.is_held, t.number),
    )
    finished = [t for t in threads if t.status not in live]
    policy = plot.get_thread_policy_display().lower()
    lines = [f"Threads ({policy}):" if screenreader else f"\n|w--- Threads ({policy}) ---|n"]
    for thread in current:
        lines.append(_thread_line(thread, screenreader))
        if thread.detail:
            lines.append(f"      {thread.detail}")
    for thread in finished:
        lines.append(_thread_line(thread, screenreader))
        if thread.status == StoryThread.Status.RESOLVED and thread.resolution:
            lines.append(f"      Resolved: {thread.resolution}")
        if thread.sealed_answer_revealed and thread.has_sealed_answer:
            lines.append(f"      The planned answer: {thread.sealed_answer}")
    return lines


def _display_thread(thread, caller):
    """Return full plot detail text for +plot <#N>."""
    is_participant = thread.is_participant(caller)
    show_ooc = is_participant or is_plot_staff(caller)
    updates = thread.updates.all()

    if uses_screenreader(caller):
        tags_str = ", ".join(tag.name for tag in thread.tags.all()) or "none"
        arc_str = f", Arc #{thread.arc.arc_number} {thread.arc.name}" if thread.arc else ""
        lines = [
            f"Plot #{thread.plot_number}: {thread.name}",
            f"  Status: {thread.get_status_display()}"
            f" | Privacy: {thread.get_privacy_display()}"
            f" | Owners: {_owner_names(thread)}{arc_str}",
            f"  Tags: {tags_str}",
        ]
        if thread.is_owner_led:
            lines.append("  Owner-led: its owners hold the answer to an open thread.")
        if thread.description:
            lines.append(f"  Tagline: {thread.description}")
        lines.extend(_thread_section(thread, caller, screenreader=True))

        if updates:
            lines.append("Updates:")
            for u in updates:
                if u.update_type == "ooc" and not show_ooc:
                    continue
                label = "OOC Note" if u.update_type == "ooc" else "IC Update"
                date_str = u.created_at.strftime("%Y-%m-%d")
                edited = f" (edited {u.edited_at.strftime('%Y-%m-%d')})" if u.edited_at else ""
                lines.append(
                    f"  {label} block {u.block_number} by {u.author_name}, {date_str}{edited}:"
                )
                lines.append(f"    {u.content}")
        else:
            lines.append("  No updates yet. Use +plot/update to add IC narrative.")

        scene_count = thread.scene_links.count()
        event_count = thread.calendar_links.count()
        post_count = thread.board_links.count()
        lines.append(
            f"Linked: {scene_count} scene(s), {event_count} event(s), {post_count} post(s)"
        )

        participants = thread.participants.filter(is_active=True).order_by("character_name")
        if participants:
            names = ", ".join(p.character_name for p in participants)
            lines.append(f"Participants: {names}")

        sequels = thread.outgoing_links.filter(link_type="sequel", is_accepted=True)
        related = thread.outgoing_links.filter(link_type="related", is_accepted=True)
        incoming_related = thread.incoming_links.filter(link_type="related", is_accepted=True)
        if sequels.exists():
            names = ", ".join(f"#{lk.to_thread.plot_number} {lk.to_thread.name}" for lk in sequels)
            lines.append(f"Sequels to: {names}")
        if related.exists() or incoming_related.exists():
            rel_set = set()
            for lk in related:
                rel_set.add(f"#{lk.to_thread.plot_number} {lk.to_thread.name}")
            for lk in incoming_related:
                rel_set.add(f"#{lk.from_thread.plot_number} {lk.from_thread.name}")
            lines.append(f"Related: {', '.join(sorted(rel_set))}")
        return "\n".join(lines)

    lines = [_format_thread_header(thread, caller)]

    if thread.description:
        lines.append(f"\n|wTagline:|n {thread.description}")

    lines.extend(_thread_section(thread, caller))

    if updates:
        lines.append("\n|w--- Updates ---")
        for u in updates:
            if u.update_type == "ooc" and not show_ooc:
                continue
            label = "OOC Note" if u.update_type == "ooc" else "IC Update"
            date_str = u.created_at.strftime("%Y-%m-%d")
            edited = (
                f" |y[Last edited: {u.edited_at.strftime('%Y-%m-%d')}]|n" if u.edited_at else ""
            )
            lines.append(
                f"|n--- {label} (Block {u.block_number}) by {u.author_name} — {date_str} ---{edited}"
            )
            lines.append(u.content)
    else:
        lines.append("\n|x(No updates yet. Use +plot/update to add IC narrative.)|n")

    scene_count = thread.scene_links.count()
    event_count = thread.calendar_links.count()
    post_count = thread.board_links.count()
    lines.append(
        f"\n|wLinked:|n {scene_count} scene(s), {event_count} event(s), {post_count} post(s)"
    )

    participants = thread.participants.filter(is_active=True).order_by("character_name")
    if participants:
        names = ", ".join(p.character_name for p in participants)
        lines.append(f"|wParticipants:|n {names}")

    sequels = thread.outgoing_links.filter(link_type="sequel", is_accepted=True)
    related = thread.outgoing_links.filter(link_type="related", is_accepted=True)
    incoming_related = thread.incoming_links.filter(link_type="related", is_accepted=True)
    pending_related = thread.incoming_links.filter(link_type="related", is_accepted=False)
    if sequels.exists():
        names = ", ".join(f"#{lk.to_thread.plot_number} {lk.to_thread.name}" for lk in sequels)
        lines.append(f"|wSequels to:|n {names}")
    if related.exists() or incoming_related.exists():
        rel_set = set()
        for lk in related:
            rel_set.add(f"#{lk.to_thread.plot_number} {lk.to_thread.name}")
        for lk in incoming_related:
            rel_set.add(f"#{lk.from_thread.plot_number} {lk.from_thread.name}")
        lines.append(f"|wRelated:|n {', '.join(sorted(rel_set))}")
    if pending_related.exists() and _can_edit_thread(thread, caller):
        pend = ", ".join(
            f"#{lk.from_thread.plot_number} {lk.from_thread.name}" for lk in pending_related
        )
        lines.append(f"|y[Pending related links from: {pend} — use +plot/accept]|n")

    if is_plot_staff(caller) and thread.hook_log:
        lines.append("\n|w[Staff] Hook log:|n")
        for entry in thread.hook_log[-5:]:
            lines.append(f"  {entry['at'][:10]}: {entry['staff']} → {entry['target']}")

    if thread.staff_log and _can_edit_thread(thread, caller):
        lines.append("\n|w[Staff actions]|n")
        for entry in thread.staff_log[-5:]:
            detail = f": {entry['detail']}" if entry.get("detail") else ""
            lines.append(f"  {entry['at'][:10]}: {entry['staff']} {entry['action']}{detail}")

    lines.append("|w" + "=" * 50 + "|n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CmdPlot
# ---------------------------------------------------------------------------


class CmdPlot(StrictSwitchMixin, MuxCommand):
    """
    Manage plots and their threads.

    Usage:
        +plot                              List active public plots
        +plot <#N|name>                    View a plot's details and threads
        +plot/list [<status>]               Filter plots by status
        +plot/create <name>[=<tagline>]    Create a new plot (proposed)
        +plot/activate <#N>               Proposed → active
        +plot/desc <#N>=<tagline>          Edit the brief tagline
        +plot/update <#N>[=<text>]         Append an IC narrative update
        +plot/note <#N>[=<text>]     Append an OOC note (participants only)
        +plot/revise <#N>/<block#>    Edit an existing update block
        +plot/tag <#N>=<tag>               Add a tag to the plot
        +plot/major <#N>=<tag>         Add a major tag (staff only)
        +plot/untag <#N>=<tag>             Remove a tag
        +plot/tags [<tag>]                 List tags, or filter plots by a tag
        +plot/privacy <#N>=<public|private|invite>
        +plot/invite <#N>=<character>      Add to invite list
        +plot/owner <#N>=<character>       Add an owner
        +plot/unowner <#N>=<character>  Remove an owner
        +plot/threads <#N>=<policy>        Set owners, request or open thread policy
        +plot/follow <#N>[=<detail>]       Follow for updates
        +plot/unfollow <#N>               Stop following
        +plot/public <#N>                 Toggle follow visibility
        +plot/scene <#N>=<scene#>     Link a scene to this plot
        +plot/post <#N>=<board>/<post>  Link a board post
        +plot/event <#N>=<event#>     Link a calendar event
        +plot/sequel <#N>=<#M>            Declare #N as sequel to #M
        +plot/relate <#N>=<#M>            Propose a related link (requires acceptance)
        +plot/accept <#N>=<#M>     Accept a pending related link from #M
        +plot/conclude <#N>               Conclude a plot (computes bonus XP)
        +plot/request-conclude <#N>       Ask staff to conclude or archive a plot
        +plot/archive <#N>               Archive a plot (staff only)

    Use +thread to view and manage questions, problems and leads inside a plot.

    A plot links scenes, board posts and calendar events into a storyline.
    Concluding a plot awards up to 5 bonus XP to all participants. Threads are
    a tool for running a plot together; they never affect XP. A held thread is
    one whose answer the owners already know; its sealed answer stays sealed
    until an owner reveals it.
    """

    key = "+plot"
    aliases = []  # noqa: RUF012
    help_category = "Storytelling"
    locks = "cmd:all()"

    # /thread formerly created a story thread; never treat it as a prefix of /threads.
    retired_switches = ("thread",)
    switch_options = (
        "list",
        "create",
        "activate",
        "desc",
        "update",
        "note",
        "revise",
        "tag",
        "major",
        "untag",
        "tags",
        "privacy",
        "invite",
        "owner",
        "unowner",
        "follow",
        "unfollow",
        "public",
        "scene",
        "post",
        "event",
        "sequel",
        "relate",
        "accept",
        "conclude",
        "request-conclude",
        "archive",
        "threads",
    )

    def func(self):
        sw = self.switches
        caller = self.caller
        args = self.args.strip()
        lhs = self.lhs.strip() if self.lhs else ""
        rhs = self.rhs.strip() if self.rhs else ""

        if not sw:
            if not args:
                return self._do_list(status_filter="active", tag_filter=None)
            thread, err = _resolve_thread(args, caller)
            if err:
                caller.msg(err)
                return
            caller.msg(_display_thread(thread, caller))
            return

        if "threads" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/threads <#N>=<owners|request|open>|n")
                return
            return self._do_thread_policy(lhs, rhs)

        if "owner" in sw or "unowner" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/owner <#N>=<character>|n")
                return
            return self._do_owner(lhs, rhs, remove="unowner" in sw)

        if "list" in sw:
            status = args.lower() or None
            if status is not None and status not in ("active", "proposed", "concluded", "archived"):
                caller.msg("Usage: +plot/list [active|proposed|concluded|archived]")
                return
            return self._do_list(status_filter=status)

        if "create" in sw:
            if not lhs:
                caller.msg("Usage: |w+plot/create <name>[=<tagline>]|n")
                return
            from evennia_plots.models import PlotThread

            thread = PlotThread.create_thread(name=lhs, creator=caller, description=rhs)
            caller.msg(
                f"|gCreated plot #{thread.plot_number}: {thread.name}|n (proposed)\n"
                f"Use |w+plot/activate #{thread.plot_number}|n to open it for contributions."
            )
            return

        if "activate" in sw:
            thread, err = _resolve_thread(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if not _can_edit_thread(thread, caller):
                caller.msg("Only the plot's owners (or staff) can activate it.")
                return
            if thread.status != "proposed":
                caller.msg(f"Plot is already {thread.get_status_display()}.")
                return
            thread.activate()
            caller.msg(f"|gPlot #{thread.plot_number} '{thread.name}' is now active.|n")
            return

        if "desc" in sw:
            thread, err = _resolve_thread(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if not _can_edit_thread(thread, caller):
                caller.msg("Only the plot's owners (or staff) can edit the tagline.")
                return
            if not rhs:
                caller.msg("Usage: |w+plot/desc <#N>=<tagline>|n")
                return
            if len(rhs) > 500:
                caller.msg("Tagline must be 500 characters or fewer.")
                return
            thread.description = rhs
            thread.save(update_fields=["description"])
            caller.msg(f"Tagline updated for #{thread.plot_number}.")
            return

        if "revise" in sw:
            return self._do_update_edit(args)

        if "update" in sw or "note" in sw:
            return self._do_update(lhs or args, rhs, "ooc" if "note" in sw else "ic")

        if "tag" in sw or "major" in sw:
            if not lhs or not rhs:
                caller.msg(f"Usage: +plot/{sw[0]} <#N>=<tag>")
                return
            return self._do_tag(lhs, rhs, make_major="major" in sw)

        if "tags" in sw:
            if args:
                return self._do_list(tag_filter=args)
            return self._do_tags()

        if "untag" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/untag <#N>=<tag>|n")
                return
            return self._do_untag(lhs, rhs)

        if "privacy" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/privacy <#N>=<public|private|invite>|n")
                return
            return self._do_privacy(lhs, rhs)

        if "invite" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/invite <#N>=<character>|n")
                return
            return self._do_invite(lhs, rhs)

        if "follow" in sw and "unfollow" not in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+plot/follow <#N>[=<detail>]|n")
                return
            return self._do_follow(lhs or args, rhs)

        if "unfollow" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+plot/unfollow <#N>|n")
                return
            return self._do_unfollow(lhs or args)

        if "public" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+plot/public <#N>|n")
                return
            return self._do_public(lhs or args)

        if sw[0] in ("scene", "post", "event"):
            if not lhs or not rhs:
                caller.msg(f"Usage: +plot/{sw[0]} <#N>=<reference>")
                return
            return getattr(self, f"_do_link_{sw[0]}")(lhs, rhs)

        if "sequel" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+plot/sequel <#N>=<#M>|n  (makes #N a sequel to #M)")
                return
            return self._do_sequel(lhs, rhs)

        if "relate" in sw or "accept" in sw:
            if not lhs or not rhs:
                caller.msg(f"Usage: +plot/{sw[0]} <#N>=<#M>")
                return
            if "accept" in sw:
                return self._do_relate_accept(lhs, rhs)
            return self._do_relate(lhs, rhs)

        if "conclude" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+plot/conclude <#N>|n")
                return
            return self._do_conclude(lhs or args)

        if "request-conclude" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+plot/request-conclude <#N>|n")
                return
            return self._do_request_conclude(lhs or args)

        if "archive" in sw:
            if not is_plot_staff(caller):
                caller.msg("Only staff can archive plots.")
                return
            if not lhs and not args:
                caller.msg("Usage: |w+plot/archive <#N>|n")
                return
            return self._do_archive(lhs or args)

        caller.msg("Unknown switch. See |w+help +plot|n for options.")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _do_list(self, status_filter=None, tag_filter=None):
        from evennia_plots.models import PlotThread

        caller = self.caller
        staff = is_plot_staff(caller)

        qs = (
            PlotThread.objects.all()
            if staff
            else PlotThread.objects.filter(
                status=PlotThread.Status.ACTIVE, privacy__in=["public", "invite_only"]
            )
        )

        if status_filter:
            qs = (
                PlotThread.objects.all().filter(status=status_filter)
                if staff
                else qs.filter(status=status_filter)
            )

        if tag_filter:
            qs = qs.filter(tags__name__icontains=tag_filter).distinct()

        threads = list(qs.prefetch_related("tags").order_by("-created_at"))

        if not threads:
            filter_desc = ""
            if tag_filter:
                filter_desc = f" with tag '{tag_filter}'"
            self.caller.msg(f"No plots found{filter_desc}.")
            return

        if uses_screenreader(caller):
            filter_label = f" (status: {status_filter})" if status_filter else ""
            filter_label += f" (tag: {tag_filter})" if tag_filter else ""
            count = len(threads)
            lines = [f"Plots{filter_label}: {count} plot{'s' if count != 1 else ''}"]
            for t in threads:
                tags_str = ", ".join(tag.name for tag in t.tags.all()) or "none"
                arc_str = f", Arc #{t.arc.arc_number} {t.arc.name}" if t.arc else ""
                scene_count = t.scene_links.count()
                lines.append(
                    f"  #{t.plot_number} {t.name}"
                    f" |lu{_plot_web_path(t.pk)}|lt[↗]|le"
                    f" — {t.get_status_display()}, Owners: {_owner_names(t)}"
                    f", Tags: {tags_str}{arc_str}, {scene_count} scene(s)"
                    f"{_thread_counts(t, caller)}"
                )
                if t.description:
                    lines.append(f"    {t.description}")
            caller.msg("\n".join(lines))
            return

        lines = ["|w== Plots ==|n"]
        for t in threads:
            tags_str = " ".join(f"|c[{tag.name}]|n" for tag in t.tags.all())
            status_color = {
                "proposed": "|y",
                "active": "|g",
                "concluded": "|b",
                "archived": "|x",
            }.get(t.status, "")
            arc_str = f" [Arc #{t.arc.arc_number}]" if t.arc else ""
            scene_count = t.scene_links.count()
            lines.append(
                f"  |w#{t.plot_number}|n {t.name}"
                f" |lu{_plot_web_path(t.pk)}|lt[↗]|le {tags_str}\n"
                f"       {status_color}{t.get_status_display()}|n"
                f" | {_owner_names(t)}{arc_str} | {scene_count} scene(s)"
                f"{_thread_counts(t, caller)}"
            )
            if t.description:
                lines.append(f"       {t.description}")
        caller.msg("\n".join(lines))

    def _do_update(self, thread_arg, inline_text, update_type):
        from evennia_plots.models import PlotUpdate

        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not thread.can_update(caller):
            if thread.status != "active":
                caller.msg(
                    f"Plot #{thread.plot_number} is {thread.get_status_display()} and not accepting updates."
                )
            else:
                caller.msg("You must be a participant or an owner to post updates.")
            return
        if update_type == "ooc" and not thread.is_participant(caller) and not is_plot_staff(caller):
            caller.msg("Only participants and staff can post OOC notes.")
            return

        if inline_text:
            block = PlotUpdate.create_update(
                parent=thread,
                author=caller,
                content=inline_text,
                update_type=update_type,
            )
            label = "OOC note" if update_type == "ooc" else "IC update"
            caller.msg(f"|gAdded {label} (block {block.block_number}) to #{thread.plot_number}.|n")
            from evennia_plots.models import PlotParticipant

            PlotParticipant.objects.get_or_create(
                thread=thread,
                character=caller,
                defaults={"character_name": caller.key},
            )
        else:
            if caller.attributes.get("plots_update_editor"):
                caller.msg("You already have an editor open. Finish it first (|w:q|n or |w:wq|n).")
                return
            caller.attributes.add(
                "plots_update_editor",
                {
                    "mode": "new",
                    "parent_model": "PlotThread",
                    "parent_pk": thread.pk,
                    "update_type": str(update_type),
                },
            )
            EvEditor(
                caller,
                loadfunc=_update_load,
                savefunc=_update_save,
                quitfunc=_update_quit,
                key="plot_update",
                persistent=True,
            )

    def _do_update_edit(self, arg):
        caller = self.caller
        if "/" not in arg:
            caller.msg("Usage: |w+plot/revise <#N>/<block#>|n")
            return
        thread_arg, _, block_str = arg.partition("/")
        if not block_str.isdigit():
            caller.msg("Block number must be an integer.")
            return
        thread, err = _resolve_thread(thread_arg.strip(), caller)
        if err:
            caller.msg(err)
            return
        from evennia_plots.models import PlotUpdate

        try:
            block = PlotUpdate.objects.get(thread=thread, block_number=int(block_str))
        except PlotUpdate.DoesNotExist:
            caller.msg(f"Block {block_str} not found on plot #{thread.plot_number}.")
            return
        if not is_plot_staff(caller) and (block.author_id is None or block.author_id != caller.id):
            caller.msg("You can only edit your own update blocks.")
            return
        if caller.attributes.get("plots_update_editor"):
            caller.msg("You already have an editor open. Finish it first (|w:q|n or |w:wq|n).")
            return
        caller.attributes.add("plots_update_editor", {"mode": "edit", "block_pk": block.pk})
        EvEditor(
            caller,
            loadfunc=_update_load,
            savefunc=_update_save,
            quitfunc=_update_quit,
            key="plot_update_edit",
            persistent=True,
        )

    def _do_tag(self, thread_arg, tag_name, make_major=False):
        caller = self.caller
        if make_major and not is_plot_staff(caller):
            caller.msg("Only staff can create major tags.")
            return
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        from evennia_plots.models import PlotTag

        tag, created = PlotTag.objects.get_or_create(
            name__iexact=tag_name,
            defaults={
                "name": tag_name,
                "is_major": make_major,
                "created_by": caller,
                "created_by_name": caller.key,
            },
        )
        if not created and make_major and not tag.is_major:
            tag.is_major = True
            tag.save(update_fields=["is_major"])
            caller.msg(f"Tag '{tag.name}' upgraded to major.")
        thread.tags.add(tag)
        action = "created and added" if created else "added"
        caller.msg(f"|gTag '{tag.name}' {action} to #{thread.plot_number}.|n")

    def _do_tags(self):
        from evennia_plots.models import PlotTag

        tags = list(PlotTag.objects.all())
        if not tags:
            self.caller.msg("No plot tags yet.")
            return
        lines = ["|w== Plot Tags ==|n", "|yMajor tags:|n"]
        major = [t for t in tags if t.is_major]
        minor = [t for t in tags if not t.is_major]
        if major:
            for t in major:
                count = t.threads.count() + t.arcs.count()
                lines.append(f"  |w{t.name}|n ({count} plot/arc(s))")
        else:
            lines.append("  (none)")
        lines.append("|wMinor tags:|n")
        if minor:
            for t in minor:
                count = t.threads.count() + t.arcs.count()
                lines.append(f"  {t.name} ({count})")
        else:
            lines.append("  (none)")
        self.caller.msg("\n".join(lines))

    def _do_untag(self, thread_arg, tag_name):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can remove tags.")
            return
        from evennia_plots.models import PlotTag

        try:
            tag = PlotTag.objects.get(name__iexact=tag_name)
        except PlotTag.DoesNotExist:
            caller.msg(f"Tag '{tag_name}' not found.")
            return
        thread.tags.remove(tag)
        caller.msg(f"Removed tag '{tag.name}' from #{thread.plot_number}.")

    def _do_privacy(self, thread_arg, privacy_val):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can change privacy.")
            return
        from evennia_plots.models import PlotThread

        mapping = {
            "public": PlotThread.Privacy.PUBLIC,
            "private": PlotThread.Privacy.PRIVATE,
            "invite": PlotThread.Privacy.INVITE_ONLY,
            "invite_only": PlotThread.Privacy.INVITE_ONLY,
        }
        choice = mapping.get(privacy_val.lower())
        if not choice:
            caller.msg("Privacy must be |wpublic|n, |wprivate|n, or |winvite|n.")
            return
        thread.privacy = choice
        thread.save(update_fields=["privacy"])
        caller.msg(f"Plot #{thread.plot_number} privacy set to {thread.get_privacy_display()}.")

    def _do_invite(self, thread_arg, char_name):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can manage invitations.")
            return
        target = caller.search(char_name, global_search=True)
        if not target:
            return
        thread.invited_characters.add(target)
        caller.msg(f"|g{target.key} invited to #{thread.plot_number}.|n")
        target.msg(
            f"|y[Plot]|n {caller.key} has invited you to contribute to: "
            f"|w{thread.name}|n (#{thread.plot_number})"
        )

    def _do_follow(self, thread_arg, detail):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        follows = caller.db.plot_follows or {}
        if thread.plot_number not in follows and len(follows) >= _MAX_PLOT_FOLLOWS:
            caller.msg(f"You can follow at most {_MAX_PLOT_FOLLOWS} plots.")
            return
        existing = follows.get(thread.plot_number, {})
        follows[thread.plot_number] = {
            "public": existing.get("public", False),
            "detail": detail if detail else existing.get("detail", ""),
            "name": thread.name,
        }
        caller.db.plot_follows = follows
        caller.msg(f"|gNow following #{thread.plot_number}: {thread.name}|n")

    def _do_unfollow(self, thread_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        follows = caller.db.plot_follows or {}
        if thread.plot_number not in follows:
            caller.msg(f"You are not following #{thread.plot_number}.")
            return
        del follows[thread.plot_number]
        caller.db.plot_follows = follows if follows else None
        caller.msg(f"Unfollowed #{thread.plot_number}: {thread.name}")

    def _do_public(self, thread_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        follows = caller.db.plot_follows or {}
        if thread.plot_number not in follows:
            caller.msg(f"You are not following #{thread.plot_number}. Use |w+plot/follow|n first.")
            return
        follows[thread.plot_number]["public"] = not follows[thread.plot_number].get("public", False)
        now_public = follows[thread.plot_number]["public"]
        caller.db.plot_follows = follows
        caller.msg(
            f"Follow of #{thread.plot_number} is now |w{'public' if now_public else 'private'}|n."
        )

    def _do_link_scene(self, thread_arg, scene_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not thread.can_link(caller):
            caller.msg(f"You don't have permission to link content to #{thread.plot_number}.")
            return
        try:
            from evennia_scenes.models import Scene
        except ImportError:
            caller.msg("Scene linking requires the evennia_scenes app to be installed.")
            return
        if not scene_arg.isdigit():
            caller.msg("Scene ID must be an integer.")
            return
        try:
            scene = Scene.objects.get(pk=int(scene_arg))
        except Scene.DoesNotExist:
            caller.msg(f"No scene #{scene_arg} found.")
            return
        from evennia_plots.models import ScenePlotLink

        _, created = ScenePlotLink.create_link(scene=scene, thread=thread, linked_by=caller)
        if created:
            caller.msg(f"|gLinked scene #{scene_arg} to plot #{thread.plot_number}.|n")
        else:
            caller.msg(f"Scene #{scene_arg} is already linked to #{thread.plot_number}.")

    def _do_link_post(self, thread_arg, post_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not thread.can_link(caller):
            caller.msg(f"You don't have permission to link content to #{thread.plot_number}.")
            return
        if _lookup_board is None:
            caller.msg("Board post linking requires the evennia_boards app to be installed.")
            return
        if "/" not in post_arg:
            caller.msg("Usage: |w+plot/post <#N>=<board#>/<post#>|n")
            return
        board_str, _, post_str = post_arg.partition("/")
        board, err = _lookup_board(board_str.strip())
        if err:
            caller.msg(err)
            return
        post, err = _lookup_post(board, post_str.strip())
        if err:
            caller.msg(err)
            return
        from evennia_plots.models import PlotBoardLink
        from evennia_plots.signals import post_linked_to_thread

        _, created = PlotBoardLink.create_link(thread, post, linked_by=caller)
        if created:
            post_linked_to_thread.send(
                sender=PlotBoardLink, thread=thread, post=post, linked_by=caller
            )
            caller.msg(f"|gLinked post {board.name}/{post.post_number} to #{thread.plot_number}.|n")
        else:
            caller.msg(f"That post is already linked to #{thread.plot_number}.")

    def _do_link_event(self, thread_arg, event_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not thread.can_link(caller):
            caller.msg(f"You don't have permission to link content to #{thread.plot_number}.")
            return
        if not event_arg.isdigit():
            caller.msg("Event ID must be an integer.")
            return
        try:
            from evennia_calendar.models import CalendarEvent
        except ImportError:
            caller.msg("Calendar event linking requires the evennia_calendar app to be installed.")
            return
        try:
            event = CalendarEvent.objects.get(pk=int(event_arg))
        except CalendarEvent.DoesNotExist:
            caller.msg(f"No calendar event #{event_arg} found.")
            return
        from evennia_plots.models import PlotCalendarLink
        from evennia_plots.signals import event_linked_to_thread

        link, created = PlotCalendarLink.create_link(thread=thread, event=event, linked_by=caller)
        if created:
            event_linked_to_thread.send(
                sender=PlotCalendarLink, thread=thread, event=event, linked_by=caller
            )
            notice = " |g(advance notice bonus met!)|n" if link.advance_notice_met else ""
            caller.msg(
                f"|gLinked event #{event_arg} ({event.title}) to #{thread.plot_number}.{notice}|n"
            )
        else:
            caller.msg(f"Event #{event_arg} is already linked to #{thread.plot_number}.")

    def _do_sequel(self, thread_arg, target_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        target, err = _resolve_thread(target_arg, caller)
        if err:
            caller.msg(err)
            return
        if thread == target:
            caller.msg("A plot cannot be a sequel to itself.")
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can add sequel links.")
            return
        from evennia_plots.models import ThreadLink

        _, created = ThreadLink.objects.get_or_create(
            from_thread=thread,
            to_thread=target,
            defaults={
                "link_type": ThreadLink.LinkType.SEQUEL,
                "created_by": caller,
                "created_by_name": caller.key,
                "is_accepted": True,
            },
        )
        if created:
            caller.msg(
                f"|gMarked #{thread.plot_number} '{thread.name}' as a sequel to "
                f"#{target.plot_number} '{target.name}'.|n"
            )
        else:
            caller.msg("A link between those plots already exists.")

    def _do_relate(self, thread_arg, target_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        target, err = _resolve_thread(target_arg, caller)
        if err:
            caller.msg(err)
            return
        if thread == target:
            caller.msg("A plot cannot be related to itself.")
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can propose related links.")
            return
        from evennia_plots.models import ThreadLink

        _, created = ThreadLink.objects.get_or_create(
            from_thread=thread,
            to_thread=target,
            defaults={
                "link_type": ThreadLink.LinkType.RELATED,
                "created_by": caller,
                "created_by_name": caller.key,
                "is_accepted": False,
            },
        )
        if created:
            caller.msg(
                f"|gProposed a related link: #{thread.plot_number} ↔ #{target.plot_number}.|n\n"
                f"An owner of '{target.name}' must accept with "
                f"|w+plot/accept #{target.plot_number}=#{thread.plot_number}|n."
            )
            for owner in _owner_characters(target, skip=caller):
                owner.msg(
                    f"|y[Plot]|n {caller.key} has proposed a 'related' link between "
                    f"#{thread.plot_number} '{thread.name}' and your plot "
                    f"#{target.plot_number} '{target.name}'.\n"
                    f"Accept with: |w+plot/accept #{target.plot_number}=#{thread.plot_number}|n"
                )
        else:
            caller.msg("A link between those plots already exists (or is pending).")

    def _do_relate_accept(self, thread_arg, from_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        from_thread, err = _resolve_thread(from_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can accept related links.")
            return
        from evennia_plots.models import ThreadLink

        try:
            link = ThreadLink.objects.get(
                from_thread=from_thread,
                to_thread=thread,
                link_type=ThreadLink.LinkType.RELATED,
                is_accepted=False,
            )
        except ThreadLink.DoesNotExist:
            caller.msg(
                f"No pending related link from #{from_thread.plot_number} to #{thread.plot_number}."
            )
            return
        link.accept(accepted_by=caller)
        caller.msg(
            f"|gAccepted related link: #{thread.plot_number} ↔ #{from_thread.plot_number}.|n"
        )
        for owner in _owner_characters(from_thread, skip=caller):
            owner.msg(
                f"|y[Plot]|n {caller.key} accepted the related link between "
                f"#{from_thread.plot_number} '{from_thread.name}' and "
                f"#{thread.plot_number} '{thread.name}'."
            )

    def _do_conclude(self, thread_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_thread(thread, caller):
            caller.msg("Only the plot's owners (or staff) can conclude it.")
            return
        if thread.status not in ("active", "proposed"):
            caller.msg(f"Plot #{thread.plot_number} is already {thread.get_status_display()}.")
            return
        try:
            bonus = thread.conclude(concluded_by=caller)
        except ValueError as exc:
            caller.msg(str(exc))
            return
        bonus_desc = []
        if thread.calendar_links.filter(advance_notice_met=True).exists():
            bonus_desc.append("+3 XP: calendar event with 1+ week advance notice")
        if thread.scene_links.count() >= 2:
            bonus_desc.append("+1 XP: multiple linked scenes")
        if thread.board_links.filter(is_ic_post=True).exists():
            bonus_desc.append("+1 XP: linked cutscene post")
        checklist = "\n  ".join(bonus_desc) if bonus_desc else "(none)"
        caller.msg(
            f"|gPlot #{thread.plot_number} '{thread.name}' concluded.|n\n"
            f"Bonus XP computed: |w{bonus}/5|n\n"
            f"Checklist:\n  {checklist}\n"
            f"|xBonus will be distributed in the next XP batch.|n"
            f"{_loose_end_note(thread)}"
        )

    def _do_request_conclude(self, thread_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        try:
            from evennia_jobs.models import Job, JobType
        except ImportError:
            caller.msg("Job ticket submission requires the evennia_jobs app to be installed.")
            return
        job = Job.create_job(
            job_type=JobType.REQUEST,
            author=caller,
            title=f"Conclude/Archive Plot #{thread.plot_number}",
            description=(
                f"Requesting that staff conclude or archive plot "
                f"#{thread.plot_number}: '{thread.name}'.\n\n"
                f"Current status: {thread.get_status_display()}\n"
                f"Creator: {thread.creator_name}"
            ),
        )
        caller.msg(
            f"|gRequest submitted as job #{job.job_number}.|n\n"
            f"Staff will review plot #{thread.plot_number} for conclusion or archival."
        )

    def _do_archive(self, thread_arg):
        caller = self.caller
        thread, err = _resolve_thread(thread_arg, caller)
        if err:
            caller.msg(err)
            return
        if thread.status == "archived":
            caller.msg(f"Plot #{thread.plot_number} is already archived.")
            return
        thread.archive()
        caller.msg(
            f"|yPlot #{thread.plot_number} '{thread.name}' archived.|n{_loose_end_note(thread)}"
        )

    # ------------------------------------------------------------------
    # Owners, thread policy and threads
    # ------------------------------------------------------------------

    def _do_owner(self, plot_arg, char_name, remove=False):
        from evennia_plots.threads import ThreadError, add_owner, remove_owner

        caller = self.caller
        plot, err = _resolve_thread(plot_arg, caller)
        if err:
            caller.msg(err)
            return
        target = caller.search(char_name, global_search=True)
        if not target:
            return
        try:
            if remove:
                remove_owner(plot, caller, target)
                caller.msg(f"{target.key} no longer owns plot #{plot.plot_number}.")
            else:
                add_owner(plot, caller, target)
                caller.msg(f"|g{target.key} now owns plot #{plot.plot_number}.|n")
        except ThreadError as exc:
            caller.msg(str(exc))

    def _do_thread_policy(self, plot_arg, policy):
        from evennia_plots.threads import ThreadError, set_policy

        caller = self.caller
        plot, err = _resolve_thread(plot_arg, caller)
        if err:
            caller.msg(err)
            return
        try:
            set_policy(plot, caller, policy.strip().lower())
        except ThreadError as exc:
            caller.msg(str(exc))
            return
        caller.msg(
            f"Threads on plot #{plot.plot_number}: |w{plot.get_thread_policy_display().lower()}|n."
        )


# ---------------------------------------------------------------------------
# CmdThread
# ---------------------------------------------------------------------------


class CmdThread(StrictSwitchMixin, MuxCommand):
    """
    Manage questions, problems and leads inside a plot.

    Usage:
        +thread <#N.T>                    View a thread
        +thread/new <#N>=<title>           Add a thread or request one
        +thread/detail <#N.T>=<text>       Set OOC detail
        +thread/accept <#N.T>              Accept a requested thread
        +thread/decline <#N.T>[=<reason>]  Decline a request
        +thread/withdraw <#N.T>            Withdraw your request
        +thread/hold <#N.T>                Toggle held status
        +thread/seal <#N.T>=<answer>       Seal an answer (empty clears it)
        +thread/answer <#N.T>              Read an answer and its history
        +thread/resolve <#N.T>=<summary>   Resolve without revealing an answer
        +thread/drop <#N.T>                Drop without revealing an answer
        +thread/reveal <#N.T>              Reveal an answer after closing
        +thread/reopen <#N.T>              Reopen a resolved or dropped thread
        +thread/lead <#N.T>                Toggle yourself as a lead
        +thread/interest <#N.T>            Toggle your interest
        +thread/carry <#N.T>=<#M>          Carry a loose end into a sequel

    Plot owners decide who may add threads with +plot/threads. Sealed answers
    stay private until an owner explicitly uses /reveal on a closed thread.
    """

    key = "+thread"
    aliases = []  # noqa: RUF012
    help_category = "Storytelling"
    locks = "cmd:all()"

    switch_options = (
        "new",
        "detail",
        "accept",
        "decline",
        "withdraw",
        "hold",
        "seal",
        "answer",
        "resolve",
        "drop",
        "reveal",
        "reopen",
        "lead",
        "interest",
        "carry",
    )

    def func(self):
        from evennia_plots import threads as svc

        caller = self.caller
        args = self.args.strip()
        lhs = self.lhs.strip() if self.lhs else ""
        rhs = self.rhs.strip() if self.rhs else ""
        action = self.switches[0] if self.switches else None
        if action == "new":
            return self._do_thread_add(lhs, rhs)
        if action is None:
            thread, err = _resolve_story_thread(args, caller)
            if err:
                caller.msg(err)
                return
            lines = [_thread_line(thread, uses_screenreader(caller))]
            if thread.detail:
                lines.append(thread.detail)
            if thread.resolution:
                lines.append(f"Resolved: {thread.resolution}")
            if thread.sealed_answer_revealed and thread.has_sealed_answer:
                lines.append(f"The planned answer: {thread.sealed_answer}")
            caller.msg("\n".join(lines))
            return

        target = lhs or args
        if not target:
            caller.msg(f"Usage: |w+thread/{action} <#N.T>|n")
            return
        thread, err = _resolve_story_thread(target, caller)
        if err:
            caller.msg(err)
            return
        try:
            if action == "detail":
                svc.set_detail(thread, caller, rhs)
                caller.msg(f"Detail updated for {thread.ref}.")
            elif action == "accept":
                svc.accept(thread, caller)
                caller.msg(f"|gThread {thread.ref} is open: {thread.title}|n")
            elif action == "decline":
                svc.decline(thread, caller, rhs)
                caller.msg(f"Declined thread request {thread.ref}.")
            elif action == "withdraw":
                ref = svc.withdraw(thread, caller)
                caller.msg(f"Withdrew your request {ref}.")
            elif action == "hold":
                svc.set_held(thread, caller, not thread.is_held)
                state = "held: its owners know the answer" if thread.is_held else "no longer held"
                caller.msg(f"Thread {thread.ref} is {state}.")
            elif action == "seal":
                svc.seal(thread, caller, rhs)
                if thread.has_sealed_answer:
                    caller.msg(
                        f"|gSealed the answer to {thread.ref}.|n Only owners and staff can read "
                        f"it until it's revealed. The thread is now held."
                    )
                else:
                    caller.msg(f"Cleared the sealed answer to {thread.ref}.")
            elif action == "answer":
                self._show_answer(thread)
            elif action == "resolve":
                if not rhs:
                    caller.msg("Usage: |w+thread/resolve <#N.T>=<summary>|n")
                    return
                svc.resolve(thread, caller, rhs, reveal_answer=False)
                caller.msg(f"|gResolved {thread.ref}: {thread.title}|n{_seal_note(thread)}")
            elif action == "drop":
                svc.drop(thread, caller, reveal_answer=False)
                caller.msg(f"Dropped {thread.ref}: {thread.title}{_seal_note(thread)}")
            elif action == "reveal":
                svc.reveal(thread, caller)
                caller.msg(f"|gRevealed the planned answer to {thread.ref}.|n")
            elif action == "reopen":
                svc.reopen(thread, caller)
                caller.msg(f"Reopened {thread.ref}: {thread.title}")
            elif action == "lead":
                leading = svc.toggle_lead(thread, caller)
                caller.msg(
                    f"You're now leading {thread.ref}."
                    if leading
                    else f"You're no longer leading {thread.ref}."
                )
            elif action == "interest":
                interested = svc.toggle_interest(thread, caller)
                caller.msg(
                    f"Marked your interest in {thread.ref}."
                    if interested
                    else f"Removed your interest in {thread.ref}."
                )
            elif action == "carry":
                self._do_thread_carry(thread, rhs)
        except svc.ThreadError as exc:
            caller.msg(str(exc))

    def _do_thread_add(self, plot_arg, title):
        from evennia_plots.models import StoryThread
        from evennia_plots.threads import ThreadError, add_thread

        caller = self.caller
        if not plot_arg or not title:
            caller.msg("Usage: |w+thread/new <#N>=<title>|n")
            return
        plot, err = _resolve_thread(plot_arg, caller)
        if err:
            caller.msg(err)
            return
        try:
            thread = add_thread(plot, caller, title)
        except ThreadError as exc:
            caller.msg(str(exc))
            return
        if thread.status == StoryThread.Status.REQUESTED:
            caller.msg(
                f"|gRequested thread {thread.ref}: {thread.title}|n\n"
                f"The plot's owners decide whether to open it."
            )
        else:
            caller.msg(f"|gAdded thread {thread.ref}: {thread.title}|n")

    def _do_thread_carry(self, thread, target_arg):
        from evennia_plots.threads import carry, carry_targets

        caller = self.caller
        if not target_arg:
            options = ", ".join(f"#{p.plot_number} {p.name}" for p in carry_targets(thread, caller))
            caller.msg(
                "Usage: |w+thread/carry <#N.T>=<#sequel>|n"
                + (f"\nSequels you could carry it into: {options}" if options else "")
            )
            return
        target, err = _resolve_thread(target_arg, caller)
        if err:
            caller.msg(err)
            return
        new, answer_carried = carry(thread, caller, target)
        note = ""
        if thread.has_sealed_answer and not answer_carried:
            note = (
                "\nThe sealed answer stayed behind: the sequel has owners who don't own "
                f"#{thread.plot.plot_number}."
            )
        caller.msg(f"|gCarried {thread.ref} into plot #{target.plot_number} as {new.ref}.|n{note}")

    def _show_answer(self, thread):
        from evennia_plots.threads import can_read_answer

        caller = self.caller
        if not can_read_answer(thread, caller):
            caller.msg(f"There's no answer to {thread.ref} you can read.")
            return
        state = "revealed" if thread.sealed_answer_revealed else "sealed"
        sealed_on = f", first sealed {thread.sealed_at:%Y-%m-%d}" if thread.sealed_at else ""
        lines = [
            f"|wAnswer to {thread.ref} {thread.title}|n ({state}{sealed_on})",
            thread.sealed_answer,
        ]
        versions = list(thread.answer_versions.order_by("-version_number"))
        if versions:
            lines.append("|wEarlier wordings:|n")
            for version in versions:
                lines.append(
                    f"  v{version.version_number} ({version.created_at:%Y-%m-%d}, "
                    f"replaced by {version.editor_name}): {version.content}"
                )
        caller.msg("\n".join(lines))


# ---------------------------------------------------------------------------
# CmdArc
# ---------------------------------------------------------------------------


class CmdArc(StrictSwitchMixin, MuxCommand):
    """
    Manage plot arcs (staff only).

    Usage:
        +arc                           List all plot arcs
        +arc <#N|name>                 View arc details
        +arc/create <name>[=<tagline>] Create a new arc (defaults to Story type)
        +arc/type <#N>=<story|downtime> Change arc type
        +arc/xp <#N>                   List XP multipliers for arc
        +arc/xp <#N>/<source>=<value>  Set per-source XP multiplier (0.0–99.99)  # noqa: RUF002
        +arc/xp <#N>/<source>=default  Clear override (revert to type default)
        +arc/current <#N>              Mark arc as the global current arc
        +arc/uncurrent                 Clear the current arc
        +arc/desc <#N>=<tagline>       Edit arc tagline
        +arc/update <#N>[=<text>]      Append an IC update block
        +arc/note <#N>[=<text>]  Append an OOC note block
        +arc/revise <#N>/<block#> Edit an existing block
        +arc/tag <#N>=<tag>            Add a tag to the arc
        +arc/untag <#N>=<tag>          Remove a tag
        +arc/link <#N>=<plot#>         Add a plot to this arc
        +arc/unlink <#N>=<plot#>       Remove a plot from this arc
        +arc/conclude <#N>             Conclude the arc
        +arc/award <#N>=<amt> # <reason>  Distribute manual XP to all arc participants
        +arc/list [<tag>]          List arcs, optional tag filter

    Plot arcs group multiple plots into a higher-level storyline.
    A Downtime arc pauses XP gain while it is active (all sources 0.0x by
    default). Use +arc/xp to override any source per arc.
    XP sources: rp_session, cutscene, lore, thread_bonus.
    Exactly one arc may be 'current' at a time.
    """  # noqa: RUF002

    key = "+arc"
    aliases = []  # noqa: RUF012
    help_category = "Storytelling"
    locks = "cmd:all()"

    switch_options = (
        "list",
        "create",
        "type",
        "xp",
        "current",
        "uncurrent",
        "desc",
        "update",
        "note",
        "revise",
        "tag",
        "untag",
        "link",
        "unlink",
        "conclude",
        "award",
    )

    def func(self):
        caller = self.caller
        if not is_plot_staff(caller):
            caller.msg("You do not have permission to use +arc.")
            return
        sw = self.switches
        args = self.args.strip()
        lhs = self.lhs.strip() if self.lhs else ""
        rhs = self.rhs.strip() if self.rhs else ""

        if not sw:
            if not args:
                return self._do_list(tag_filter=None)
            arc, err = _resolve_arc(args, caller)
            if err:
                caller.msg(err)
                return
            caller.msg(self._display_arc(arc))
            return

        if "list" in sw:
            tag_filter = args or None
            return self._do_list(tag_filter=tag_filter)

        if "create" in sw:
            if not lhs:
                caller.msg("Usage: |w+arc/create <name>[=<tagline>]|n")
                return
            if not can_manage_arc(caller):
                caller.msg("You do not have permission to create arcs.")
                return
            arc = PlotArc.create_arc(name=lhs, creator=caller, description=rhs)
            caller.msg(f"|gCreated arc #{arc.arc_number}: {arc.name} [Story]|n")
            return

        if "type" in sw:
            arc, err = _resolve_arc(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if not can_manage_arc(caller, arc):
                caller.msg("You do not have permission to change this arc's type.")
                return
            if not rhs:
                caller.msg("Usage: |w+arc/type <#N>=<story|downtime>|n")
                return
            valid = [v for v, _ in PlotArc.ArcType.choices]
            if rhs.lower() not in valid:
                caller.msg(f"Unknown arc type '{rhs}'. Valid values: {', '.join(valid)}.")
                return
            old_type = arc.arc_type
            new_type = rhs.lower()
            if old_type == new_type:
                caller.msg(f"Arc #{arc.arc_number} is already type '{new_type}'.")
                return
            arc.arc_type = new_type
            arc.save(update_fields=["arc_type"])
            arc_type_changed.send(sender=type(arc), arc=arc, old_type=old_type, new_type=new_type)
            xp_note = " |y(XP now paused)|n" if arc.pauses_xp else ""
            caller.msg(f"|gArc #{arc.arc_number} type changed to '{new_type}'.{xp_note}|n")
            return

        if "xp" in sw:
            arc_arg, address, source = (lhs or args).partition("/")
            if (self.rhs is not None and not address) or (address and not rhs):
                caller.msg("Usage: +arc/xp <#N>/<source>=<value|default>, or +arc/xp <#N> to list.")
                return
            arc, err = _resolve_arc(arc_arg, caller)
            if err:
                caller.msg(err)
                return
            if not can_manage_arc(caller, arc):
                caller.msg("You do not have permission to set XP multipliers.")
                return
            source_labels = PlotArc.XP_SOURCE_LABELS
            if not address:
                lines = [
                    f"|wXP multipliers for arc #{arc.arc_number} ({arc.get_arc_type_display()} defaults):|n"
                ]
                for source in PlotArc.XP_SOURCES:
                    override = getattr(arc, f"xp_mult_{source}")
                    effective = arc.get_xp_multiplier(source)
                    if override is not None:
                        lines.append(
                            f"  {source_labels[source]}: |c{override}x|n |y(override; type default {PlotArc.TYPE_DEFAULT_MULTIPLIERS[arc.arc_type][source]}x)|n"
                        )
                    else:
                        lines.append(f"  {source_labels[source]}: {effective}x (type default)")
                caller.msg("\n".join(lines))
                return
            source = source.strip().lower()
            value_str = rhs
            if source not in PlotArc.XP_SOURCES:
                caller.msg(f"Unknown source '{source}'. Valid: {', '.join(PlotArc.XP_SOURCES)}.")
                return
            field = f"xp_mult_{source}"
            if value_str.lower() in ("default", "none", "clear"):
                setattr(arc, field, None)
                arc.save(update_fields=[field])
                caller.msg(
                    f"|gArc #{arc.arc_number} {source_labels[source]} XP multiplier cleared (reverts to type default).|n"
                )
                return
            try:
                value = Decimal(value_str)
            except InvalidOperation:
                caller.msg(f"'{value_str}' is not a valid decimal number.")
                return
            if not value.is_finite():
                caller.msg("Multiplier must be a finite decimal number.")
                return
            if value < 0:
                caller.msg("Multiplier cannot be negative.")
                return
            if value > Decimal("99.99"):
                caller.msg("Multiplier cannot exceed 99.99.")
                return
            setattr(arc, field, value)
            arc.save(update_fields=[field])
            caller.msg(
                f"|gArc #{arc.arc_number} {source_labels[source]} XP multiplier set to {value}x.|n"
            )
            return

        if "uncurrent" in sw:
            if not can_manage_arc(caller):
                caller.msg("You do not have permission to change the current arc.")
                return
            if args or lhs:
                caller.msg(
                    "|y+arc/uncurrent takes no arguments — it always clears the global current arc.|n"
                )
                return
            current = PlotArc.objects.filter(is_current=True).first()
            if not current:
                caller.msg("There is no current arc to clear.")
                return
            current.is_current = False
            current.save(update_fields=["is_current"])
            arc_currency_changed.send(sender=type(current), arc=current, became_current=False)
            caller.msg(f"|gArc #{current.arc_number} is no longer the current arc.|n")
            return

        if "current" in sw:
            arc, err = _resolve_arc(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if not can_manage_arc(caller, arc):
                caller.msg("You do not have permission to set the current arc.")
                return
            if arc.status != PlotArc.Status.ACTIVE:
                caller.msg("Only an Active arc can be made current.")
                return
            if arc.is_current:
                caller.msg(f"Arc #{arc.arc_number} is already the current arc.")
                return
            # Defer both signals to on_commit so listeners only see committed state.
            with transaction.atomic():
                demoted = (
                    PlotArc.objects.select_for_update()
                    .filter(is_current=True)
                    .exclude(pk=arc.pk)
                    .first()
                )
                if demoted:
                    demoted.is_current = False
                    demoted.save(update_fields=["is_current"])
                    transaction.on_commit(
                        lambda d=demoted: arc_currency_changed.send(
                            sender=type(d), arc=d, became_current=False
                        )
                    )
                arc.is_current = True
                arc.save(update_fields=["is_current"])
                transaction.on_commit(
                    lambda: arc_currency_changed.send(
                        sender=type(arc), arc=arc, became_current=True
                    )
                )
            xp_note = " |y(XP paused — Downtime arc)|n" if arc.pauses_xp else ""
            caller.msg(f"|gArc #{arc.arc_number} '{arc.name}' is now the current arc.{xp_note}|n")
            return

        if "desc" in sw:
            arc, err = _resolve_arc(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if not rhs:
                caller.msg("Usage: |w+arc/desc <#N>=<tagline>|n")
                return
            if len(rhs) > 500:
                caller.msg("Tagline must be 500 characters or fewer.")
                return
            arc.description = rhs
            arc.save(update_fields=["description"])
            caller.msg(f"Tagline updated for arc #{arc.arc_number}.")
            return

        if "revise" in sw:
            return self._do_update_edit(args)

        if "update" in sw or "note" in sw:
            return self._do_update(lhs or args, rhs, "ooc" if "note" in sw else "ic")

        if "tag" in sw and "untag" not in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+arc/tag <#N>=<tag>|n")
                return
            arc, err = _resolve_arc(lhs, caller)
            if err:
                caller.msg(err)
                return
            from evennia_plots.models import PlotTag

            tag, _ = PlotTag.objects.get_or_create(
                name__iexact=rhs,
                defaults={
                    "name": rhs,
                    "created_by": caller,
                    "created_by_name": caller.key,
                },
            )
            arc.tags.add(tag)
            caller.msg(f"|gTag '{tag.name}' added to arc #{arc.arc_number}.|n")
            return

        if "untag" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+arc/untag <#N>=<tag>|n")
                return
            arc, err = _resolve_arc(lhs, caller)
            if err:
                caller.msg(err)
                return
            from evennia_plots.models import PlotTag

            try:
                tag = PlotTag.objects.get(name__iexact=rhs)
            except PlotTag.DoesNotExist:
                caller.msg(f"Tag '{rhs}' not found.")
                return
            arc.tags.remove(tag)
            caller.msg(f"Removed tag '{tag.name}' from arc #{arc.arc_number}.")
            return

        if "link" in sw and "unlink" not in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+arc/link <arc#>=<plot#>|n")
                return
            arc, err = _resolve_arc(lhs, caller)
            if err:
                caller.msg(err)
                return
            thread, err = _resolve_thread(rhs, caller)
            if err:
                caller.msg(err)
                return
            thread.arc = arc
            thread.save(update_fields=["arc"])
            caller.msg(f"|gPlot #{thread.plot_number} added to arc #{arc.arc_number}.|n")
            return

        if "unlink" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+arc/unlink <arc#>=<plot#>|n")
                return
            arc, err = _resolve_arc(lhs, caller)
            if err:
                caller.msg(err)
                return
            thread, err = _resolve_thread(rhs, caller)
            if err:
                caller.msg(err)
                return
            if thread.arc_id != arc.id:
                caller.msg(f"Plot #{thread.plot_number} is not in arc #{arc.arc_number}.")
                return
            thread.arc = None
            thread.save(update_fields=["arc"])
            caller.msg(f"Plot #{thread.plot_number} removed from arc #{arc.arc_number}.")
            return

        if "conclude" in sw:
            arc, err = _resolve_arc(lhs or args, caller)
            if err:
                caller.msg(err)
                return
            if arc.status == "concluded":
                caller.msg(f"Arc #{arc.arc_number} is already concluded.")
                return
            arc.conclude()
            caller.msg(f"|gArc #{arc.arc_number} '{arc.name}' concluded.|n")
            return

        if "award" in sw:
            return self._do_award(lhs or args, rhs)

        caller.msg("Unknown switch. See |w+help +arc|n for options.")

    def _do_award(self, arc_arg, rhs):
        """Distribute a manual XP grant to every PlotParticipant in arc's threads.

        Each participant receives a MANUAL_GRANT XPLog row tagged with the arc
        number in the reason, attributed to the calling staff member. The
        command can be re-run for staged payouts at multi-stage arc milestones;
        no idempotency lock per (arc, character) — by design, this is a manual
        staff tool (collect_arc_bonuses is a no-op stub).
        """
        caller = self.caller
        arc, err = _resolve_arc(arc_arg, caller)
        if err:
            caller.msg(err)
            return
        if not can_manage_arc(caller, arc):
            caller.msg("You do not have permission to award arc XP.")
            return
        if not rhs:
            caller.msg(
                "Usage: |w+arc/award <#N>=<amount> # <reason>|n  "
                "(distributes manually to every participant)"
            )
            return

        try:
            from evennia_xp.awards import record_xp
            from evennia_xp.models import XPLog
        except ImportError:
            caller.msg("XP award requires the evennia_xp app to be installed.")
            return

        from evennia_plots.models import PlotParticipant

        amt_str, extra_reason = split_comment(rhs)
        try:
            amount = Decimal(amt_str)
        except InvalidOperation:
            caller.msg(f"|r'{amt_str}' is not a valid XP amount.|n")
            return
        if not amount.is_finite() or amount <= 0:
            caller.msg("|rArc award amount must be positive.|n")
            return

        thread_ids = list(arc.threads.values_list("pk", flat=True))
        if not thread_ids:
            caller.msg(f"Arc #{arc.arc_number} has no plots — nothing to award.")
            return

        recipient_ids = sorted(
            set(
                PlotParticipant.objects.filter(
                    thread_id__in=thread_ids,
                    character_id__isnull=False,
                ).values_list("character_id", flat=True)
            )
        )
        if not recipient_ids:
            caller.msg(f"Arc #{arc.arc_number} has no participants to award.")
            return

        base_reason = f"plot_arc_#{arc.arc_number}"
        full_reason = f"{base_reason}: {extra_reason}" if extra_reason else base_reason

        from evennia.utils.search import search_object

        granted = 0
        for char_id in recipient_ids:
            results = search_object(f"#{char_id}")
            char_name = results[0].key if results else ""
            log = record_xp(
                character_id=char_id,
                amount=amount,
                source_type=XPLog.SourceType.MANUAL_GRANT,
                source_ref_id=0,
                reason=full_reason,
                character_name=char_name,
                granted_by=caller,
            )
            if log is not None:
                granted += 1

        total_xp = amount * granted
        caller.msg(
            f"|gArc #{arc.arc_number}: awarded {amount} XP to {granted} "
            f"participant(s) ({total_xp} XP total).|n  Reason: {full_reason}"
        )

    def _do_list(self, tag_filter=None):
        from evennia_plots.models import PlotArc

        qs = PlotArc.objects.prefetch_related("tags")
        if tag_filter:
            qs = qs.filter(tags__name__icontains=tag_filter).distinct()
        arcs = list(qs)
        if not arcs:
            self.caller.msg("No plot arcs found.")
            return
        lines = ["|w== Plot Arcs ==|n"]
        for a in arcs:
            tags_str = " ".join(f"|c[{t.name}]|n" for t in a.tags.all()) or ""
            thread_count = a.threads.count()
            current_marker = " |y[Current]|n" if a.is_current else ""
            type_badge = f"|m{a.get_arc_type_display()}|n"
            lines.append(
                f"  |w#{a.arc_number}|n {a.name} {type_badge}{current_marker} {tags_str} "
                f"[{a.get_status_display()}] {thread_count} plot(s)"
            )
            if a.description:
                lines.append(f"       {a.description}")
        self.caller.msg("\n".join(lines))

    def _display_arc(self, arc):
        tags = " ".join(f"|c[{t.name}]|n" for t in arc.tags.all()) or "|x(no tags)|n"
        current_marker = " |y[Current]|n" if arc.is_current else ""
        type_badge = f"|m{arc.get_arc_type_display()}|n"
        lines = [
            f"|w== Arc #{arc.arc_number}: {arc.name} ==|n",
            f"Tags: {tags}",
            f"Status: {arc.get_status_display()} | Type: {type_badge}{current_marker} | Creator: {arc.creator_name}",
        ]
        if arc.pauses_xp:
            lines.append("|y** XP gain paused (Downtime arc) **|n")
        overrides = {
            s: getattr(arc, f"xp_mult_{s}")
            for s in PlotArc.XP_SOURCES
            if getattr(arc, f"xp_mult_{s}") is not None
        }
        if overrides:
            override_parts = [f"{PlotArc.XP_SOURCE_LABELS[s]}: {v}x" for s, v in overrides.items()]
            lines.append(f"|cXP overrides:|n {', '.join(override_parts)}")
        if arc.description:
            lines.append(f"\n|wTagline:|n {arc.description}")

        caller = self.caller
        show_ooc = is_plot_staff(caller)
        updates = arc.updates.all()
        if updates:
            lines.append("\n|w--- Updates ---")
            for u in updates:
                if u.update_type == "ooc" and not show_ooc:
                    continue
                label = "OOC Note" if u.update_type == "ooc" else "IC Update"
                date_str = u.created_at.strftime("%Y-%m-%d")
                edited = (
                    f" |y[Last edited: {u.edited_at.strftime('%Y-%m-%d')}]|n" if u.edited_at else ""
                )
                lines.append(
                    f"|n--- {label} (Block {u.block_number}) by {u.author_name} — {date_str} ---{edited}"
                )
                lines.append(u.content)

        threads = list(arc.threads.order_by("status", "-created_at"))
        lines.append(f"\n|wPlots ({len(threads)}):|n")
        for t in threads:
            lines.append(f"  #{t.plot_number} {t.name} [{t.get_status_display()}]")
        if not threads:
            lines.append("  (none)")

        lines.append("|w" + "=" * 50 + "|n")
        return "\n".join(lines)

    def _do_update(self, arc_arg, inline_text, update_type):
        from evennia_plots.models import PlotUpdate

        caller = self.caller
        arc, err = _resolve_arc(arc_arg, caller)
        if err:
            caller.msg(err)
            return
        if inline_text:
            block = PlotUpdate.create_update(
                parent=arc, author=caller, content=inline_text, update_type=update_type
            )
            label = "OOC note" if update_type == "ooc" else "IC update"
            caller.msg(f"|gAdded {label} (block {block.block_number}) to arc #{arc.arc_number}.|n")
        else:
            if caller.attributes.get("plots_update_editor"):
                caller.msg("You already have an editor open. Finish it first.")
                return
            caller.attributes.add(
                "plots_update_editor",
                {
                    "mode": "new",
                    "parent_model": "PlotArc",
                    "parent_pk": arc.pk,
                    "update_type": str(update_type),
                },
            )
            EvEditor(
                caller,
                loadfunc=_update_load,
                savefunc=_update_save,
                quitfunc=_update_quit,
                key="arc_update",
                persistent=True,
            )

    def _do_update_edit(self, arg):
        caller = self.caller
        if "/" not in arg:
            caller.msg("Usage: |w+arc/revise <#N>/<block#>|n")
            return
        arc_arg, _, block_str = arg.partition("/")
        if not block_str.isdigit():
            caller.msg("Block number must be an integer.")
            return
        arc, err = _resolve_arc(arc_arg.strip(), caller)
        if err:
            caller.msg(err)
            return
        from evennia_plots.models import PlotUpdate

        try:
            block = PlotUpdate.objects.get(arc=arc, block_number=int(block_str))
        except PlotUpdate.DoesNotExist:
            caller.msg(f"Block {block_str} not found on arc #{arc.arc_number}.")
            return
        if caller.attributes.get("plots_update_editor"):
            caller.msg("You already have an editor open. Finish it first.")
            return
        caller.attributes.add("plots_update_editor", {"mode": "edit", "block_pk": block.pk})
        EvEditor(
            caller,
            loadfunc=_update_load,
            savefunc=_update_save,
            quitfunc=_update_quit,
            key="arc_update_edit",
            persistent=True,
        )


# ---------------------------------------------------------------------------
# CmdHook
# ---------------------------------------------------------------------------


class CmdHook(StrictSwitchMixin, MuxCommand):
    """
    Nudge a player toward a plot (staff only).

    Usage:
        +hook <#N|name>=<character>

    Sends a suggestion to a specific player encouraging them to look into
    an existing plot. Cannot be used for private plots.

    A staff-visible record is kept in the plot's hook_log to prevent
    favoritism tracking (visible via +plot <#N> when logged in as staff).
    """

    key = "+hook"
    aliases = ["+prompt", "+nudge"]  # noqa: RUF012
    help_category = "Storytelling"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        if not is_plot_staff(caller):
            caller.msg("You do not have permission to use +hook.")
            return
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+hook <#N|name>=<character>|n")
            return

        thread, err = _resolve_thread(self.lhs.strip(), caller)
        if err:
            caller.msg(err)
            return

        if thread.privacy == "private":
            caller.msg("You cannot hook players toward a private plot.")
            return

        target = caller.search(self.rhs.strip(), global_search=True)
        if not target:
            return

        target.msg(
            f"|y[Staff Hook]|n {caller.key} suggests you look into: "
            f"|w{thread.name}|n (#{thread.plot_number})"
        )

        # Capped at 50 entries to prevent unbounded growth.
        log = thread.hook_log or []
        log.append(
            {
                "staff": caller.key,
                "target": target.key,
                "at": timezone.now().isoformat(),
            }
        )
        thread.hook_log = log[-50:]
        thread.save(update_fields=["hook_log"])

        caller.msg(f"|gHook sent to {target.key} for plot #{thread.plot_number}.|n")
