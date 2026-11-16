# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Calendar-owned live authorization, action state and safe inbox presentation."""

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeAction,
    NoticeEvent,
    RenderedNotice,
    SubjectRef,
    authorize_context,
)


def event_for(row):
    """Reconstruct the immutable source envelope; live titles never alter identity."""
    data = row.envelope
    return NoticeEvent(
        event_id=data["event_id"],
        occurred_at=parse_datetime(data["occurred_at"]),
        subject=SubjectRef(**data["subject"]),
        actors=tuple(ActorRef(**actor) for actor in data["actors"]),
        payload=data["payload"],
        replacement_key=data.get("replacement_key"),
        action_kind=data.get("action_kind"),
    )


def currentness(row, now=None):
    """Check source lifecycle before viewer state, including background maintenance."""
    now = now or timezone.now()
    rsvp, event = row.rsvp, row.rsvp.event
    if (
        rsvp.character_id != row.character_id
        or rsvp.status != row.status
        or event.is_cancelled
        or event.scheduled_time <= now
    ):
        return Evaluation("invalid")
    if row.kind in {"drawn", "invited"} and event.confirmation_deadline <= now:
        return Evaluation("invalid")
    if row.envelope and row.envelope.get("payload", {}).get("event") != rsvp.event_id:
        return Evaluation("invalid")
    expected_status = {
        "lottery": "lottery_selected",
        "waitlist_offer": "invited",
        "invitation": "invited",
        "seated": "confirmed",
        "reminder": "confirmed",
    }.get(row.origin)
    if expected_status is not None and row.status != expected_status:
        return Evaluation("invalid")
    if row.generation is not None and row.generation != rsvp.notice_generation:
        return Evaluation("invalid")
    if row.generation is None or not row.provenance_known:
        return Evaluation("defer", reason="provenance")
    return Evaluation("visible", outstanding=row.origin in {"lottery", "waitlist_offer"})


def same_envelope(event, row):
    """Reject forged actors, actions or recipient even when the source pk is real."""
    expected = event_for(row)
    return (
        event.recipient_kind == "character"
        and event.recipient_id == row.character_id
        and all(
            getattr(event, name) == getattr(expected, name)
            for name in (
                "event_id",
                "occurred_at",
                "subject",
                "actors",
                "payload",
                "replacement_key",
                "action_kind",
            )
        )
    )


class CalendarNoticeSource:
    """One Calendar batch, always scoped to its addressed playable character."""

    label = "Calendar"

    def prepare(self, context):
        """Transfer only this actual selected character before its first summary."""
        if context.character is not None and authorize_context(context, context.character):
            from evennia_calendar.notices import transfer_pending

            transfer_pending(context.character, context=context)

    def evaluate(self, events, context):
        """Validate authoritative envelope and live state before text or counts."""
        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        from evennia_calendar.models import CalendarNotice

        ids = {e.payload.get("notice") for e in events if type(e.payload.get("notice")) is int}
        rows = CalendarNotice.objects.filter(pk__in=ids).select_related("rsvp__event").in_bulk()
        actor_ids = {"account": set(), "character": set()}
        for row in rows.values():
            for actor in row.actors:
                if actor.get("kind") in actor_ids:
                    actor_ids[actor["kind"]].add(actor.get("id"))
        existing = {
            "account": set(
                AccountDB.objects.filter(pk__in=actor_ids["account"]).values_list("pk", flat=True)
            ),
            "character": set(
                ObjectDB.objects.filter(pk__in=actor_ids["character"]).values_list("pk", flat=True)
            ),
        }
        result = {}
        for event in events:
            row = rows.get(event.payload.get("notice"))
            try:
                if row is None or not same_envelope(event, row):
                    outcome = Evaluation("invalid")
                else:
                    outcome = currentness(row)
                    if outcome.status == "visible" and any(
                        actor["id"] not in existing[actor["kind"]] for actor in row.actors
                    ):
                        outcome = Evaluation("defer", reason="provenance")
                    if outcome.status == "visible" and (
                        getattr(context.character, "pk", None) != row.character_id
                        or not authorize_context(context)
                    ):
                        outcome = Evaluation("defer", reason="context")
            except (KeyError, TypeError, ValueError):
                outcome = Evaluation("defer", reason="provenance")
            result[event.event_id] = outcome
        return result

    def render(self, events, context):
        """Render only eligible constituents; no historical sender names are exposed."""
        from evennia_calendar import notices
        from evennia_calendar.models import CalendarNotice

        rows = (
            CalendarNotice.objects.filter(pk__in=[e.payload["notice"] for e in events])
            .select_related("rsvp__event")
            .in_bulk()
        )
        if len(events) > 1:
            return RenderedNotice(
                f"{len(events)} Calendar updates. Check your calendar for current events.",
                (NoticeAction("Your calendar", command="+calendar/mine"),),
            )
        row = rows[events[0].payload["notice"]]
        event = row.rsvp.event
        messages = {
            "lottery": notices.drawn_message,
            "waitlist_offer": notices.offered_message,
            "invitation": notices.invited_message,
            "seated": notices.seated_message,
            "reminder": notices.reminder_message,
        }
        text = messages[row.origin](event)
        actions = [
            NoticeAction(
                "View event",
                command=f"+calendar {event.pk}",
                route_name="evennia_calendar:calendar-event-detail",
                route_args=(event.pk,),
            )
        ]
        if row.origin in {"lottery", "waitlist_offer", "invitation"}:
            actions += [
                NoticeAction("Confirm place", command=f"+rsvp/confirm {event.pk}"),
                NoticeAction("Decline place", command=f"+rsvp/cancel {event.pk}"),
            ]
        return RenderedNotice(text, tuple(actions))
