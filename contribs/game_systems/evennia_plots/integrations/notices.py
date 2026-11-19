# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Typed Plots events, current witnesses and shared Inbox presentation."""

from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeAction,
    NoticeEvent,
    RenderedNotice,
    StoredEvent,
    SubjectRef,
    authorize_context,
    evaluate,
    normalize_rendered,
)

from ..models import PlotNoticeReceipt, PlotOwner, PlotThread, StoryThread

SOURCE = "plots"
Kind = PlotNoticeReceipt.Kind
State = PlotNoticeReceipt.State
LIVE_PLOT = (PlotThread.Status.PROPOSED, PlotThread.Status.ACTIVE)
ACCEPTED_THREAD = (
    StoryThread.Status.OPEN,
    StoryThread.Status.RESOLVED,
    StoryThread.Status.DROPPED,
    StoryThread.Status.LOOSE_END,
    StoryThread.Status.CARRIED,
)


def event_key(row):
    if row.kind == Kind.REQUEST:
        return f"plot-request-{row.thread_id}-{row.owner_id}"
    if row.kind == Kind.GRANT:
        return f"plot-owner-grant-{row.owner_id}"
    return f"plot-thread-decision-{row.thread_id}"


def event_for(row):
    grant = row.kind == Kind.GRANT
    subject = (
        SubjectRef("plot-owner", str(row.owner_id))
        if grant
        else SubjectRef("story-thread", str(row.thread_id))
    )
    return NoticeEvent(
        event_key(row),
        row.occurred_at,
        subject,
        (ActorRef("character", row.actor_id),),
        {
            "character": row.character_id,
            "plot": row.plot_id,
            "kind": row.kind,
            "owner": row.owner_id,
        },
        replacement_key=f"plot-owner-{row.plot_id}-{row.character_id}" if grant else None,
    )


def stored_event(row):
    return StoredEvent(
        **vars(event_for(row)), recipient_kind="character", recipient_id=row.character_id
    )


class Witnesses:
    """Load mutable subjects separately from source state and its writer locks."""

    def __init__(self, rows):
        self._visible_plots = {}
        self.plots = PlotThread.objects.in_bulk({row.plot_id for row in rows})
        self.threads = StoryThread.objects.in_bulk({row.thread_id for row in rows if row.thread_id})
        self.owners = PlotOwner.objects.in_bulk({row.owner_id for row in rows if row.owner_id})
        self.objects = ObjectDB.objects.in_bulk(
            {pk for row in rows for pk in (row.actor_id, row.character_id)}
        )

    def status(self, row):
        from ..threads import can_view_thread

        plot = self.plots.get(row.plot_id)
        actor = self.objects.get(row.actor_id)
        character = self.objects.get(row.character_id)
        if (
            plot is None
            or actor is None
            or character is None
            or row.actor_id == row.character_id
            or row.event_key != event_key(row)
        ):
            return "invalid"

        thread = self.threads.get(row.thread_id)
        owner = self.owners.get(row.owner_id)
        if row.kind in (Kind.REQUEST, Kind.GRANT) and (
            owner is None or owner.plot_id != row.plot_id or owner.character_id != character.pk
        ):
            return "invalid"
        if row.kind == Kind.GRANT:
            if row.thread_id is not None or owner.added_by_id != actor.pk:
                return "invalid"
        else:
            if thread is None or thread.plot_id != row.plot_id:
                return "invalid"
            if row.kind == Kind.REQUEST:
                if (
                    thread.created_by_id != actor.pk
                    or thread.status != StoryThread.Status.REQUESTED
                ):
                    return "invalid"
                if plot.status not in LIVE_PLOT:
                    return "hidden"
            else:
                if (
                    row.kind not in (Kind.ACCEPT, Kind.DECLINE)
                    or row.owner_id is not None
                    or thread.created_by_id != character.pk
                    or thread.decided_by_id != actor.pk
                ):
                    return "invalid"
                statuses = (
                    ACCEPTED_THREAD if row.kind == Kind.ACCEPT else (StoryThread.Status.DECLINED,)
                )
                if thread.status not in statuses:
                    return "invalid"
            thread.plot = plot
            if not can_view_thread(thread, character, manages=row.kind == Kind.REQUEST):
                return "hidden"
        viewer = row.plot_id, row.character_id
        if viewer not in self._visible_plots:
            self._visible_plots[viewer] = plot.can_view(character)
        return "visible" if self._visible_plots[viewer] else "hidden"

    def presentation(self, row, *, standalone=False):
        plot = self.plots[row.plot_id]
        thread = self.threads.get(row.thread_id)
        ref = thread.ref if thread else f"#{plot.plot_number}"
        action = NoticeAction(
            "View thread" if thread else "View plot",
            command=f"+thread {ref}" if thread else f"+plot {ref}",
        )
        if row.kind == Kind.REQUEST:
            action = NoticeAction("Review thread request", command=f"+thread {ref}")
            text = f"A thread request is ready for review ({ref})."
        elif row.kind == Kind.ACCEPT:
            text = f"Your thread request {ref} was accepted."
        elif row.kind == Kind.DECLINE:
            text = f"Your thread request {ref} was declined."
        else:
            text = f"You were made an owner of plot {ref}."

        if standalone:
            if row.kind == Kind.REQUEST:
                actor = self.objects[row.actor_id]
                text = (
                    f"{actor.key} asks to open thread {ref} on {plot.name}: {thread.title}\n"
                    f"Accept with +thread/accept {ref} or decline with "
                    f"+thread/decline {ref}=<reason>."
                )
            elif row.kind == Kind.ACCEPT:
                text = f"Your thread {ref} on {plot.name} was accepted: {thread.title}"
            elif row.kind == Kind.DECLINE:
                because = f" ({thread.decline_reason})" if thread.decline_reason else ""
                text = f"Your thread request {ref} on {plot.name} was declined{because}."
            else:
                actor = self.objects[row.actor_id]
                text = f"{actor.key} made you an owner of {plot.name} ({ref})."
            text = f"[Plot] {text}"
        elif plot.privacy == PlotThread.Privacy.PRIVATE:
            text = {
                Kind.REQUEST: f"A private plot has a thread request for review ({ref}).",
                Kind.ACCEPT: f"Your thread request on a private plot was accepted ({ref}).",
                Kind.DECLINE: f"Your thread request on a private plot was declined ({ref}).",
                Kind.GRANT: f"You were made an owner of a private plot ({ref}).",
            }[row.kind]
        return normalize_rendered(RenderedNotice(text, (action,)))


def _matches(row, event):
    if stored_event(row) != event:
        return False
    # Equality alone conflates boolean payload values with integer IDs.
    return (
        type(event.payload["character"]) is int
        and type(event.payload["plot"]) is int
        and (event.payload["owner"] is None or type(event.payload["owner"]) is int)
        and type(event.actors[0].id) is int
    )


def _load_rows(events):
    recipients = {event.recipient_id for event in events if type(event.recipient_id) is int}
    keys = {event.event_id for event in events if isinstance(event.event_id, str)}
    return {
        (row.character_id, row.event_key): row
        for row in PlotNoticeReceipt.objects.filter(
            character_id__in=recipients, event_key__in=keys, state__in=(State.PENDING, State.INBOX)
        )
    }


def _authorized_character(context):
    if context.character is None or not isinstance(context.account, AccountDB):
        return False
    context.account.attributes.reset_cache()
    return authorize_context(context)


class PlotNoticeSource:
    label = "Plots"

    def prepare(self, context):
        from ..notices import prepare

        prepare(context)

    def evaluate(self, events, context):
        rows = _load_rows(events)
        witnesses = Witnesses(rows.values())
        character_id = getattr(context.character, "pk", None)
        account_id = getattr(context.account, "pk", None)
        authorized = _authorized_character(context)
        outcomes = {}
        for event in events:
            row = None
            if type(event.recipient_id) is int and isinstance(event.event_id, str):
                row = rows.get((event.recipient_id, event.event_id))
            if row is None or not _matches(row, event):
                outcome = Evaluation("invalid")
            else:
                status = witnesses.status(row)
                if status != "visible":
                    outcome = Evaluation(status)
                elif context.account is None:
                    outcome = Evaluation("defer", reason="context")
                elif (
                    not authorized
                    or row.character_id != character_id
                    or account_id in row.suppressed_accounts
                ):
                    outcome = Evaluation("hidden")
                else:
                    outcome = Evaluation("visible")
            outcomes[event.event_id] = outcome
        return outcomes

    def render(self, events, context):
        outcomes = evaluate(self, events, context)
        visible = [event for event in events if outcomes[event.event_id].status == "visible"]
        if not _authorized_character(context):
            raise ValueError("No current plot notice to render")
        rows = _load_rows(visible)
        witnesses = Witnesses(rows.values())
        eligible = [
            row
            for row in rows.values()
            if getattr(context.account, "pk", None) not in row.suppressed_accounts
            and witnesses.status(row) == "visible"
        ]
        if not eligible:
            raise ValueError("No current plot notice to render")
        if len(eligible) == 1:
            return witnesses.presentation(eligible[0])
        return normalize_rendered(
            RenderedNotice(
                "There is new plot activity.", (NoticeAction("View plots", "+plot/list"),)
            )
        )
