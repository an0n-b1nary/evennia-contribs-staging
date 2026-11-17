# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Account-owned historical outcomes, with identity-safe live presentation."""

import json
from hashlib import sha256

from django.utils.dateparse import parse_datetime

from evennia_links.identity import comms_identity
from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeEvent,
    RenderedNotice,
    StoredEvent,
    SubjectRef,
    authorize_context,
    validate_event,
)

KINDS = {"approved", "declined", "lapsed", "example"}


def event_for(row):
    """Reference the source snapshot without carrying its text in the inbox."""
    data = row.envelope
    payload = data["payload"]
    snapshot = json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":"))
    event = NoticeEvent(
        data["event_id"],
        parse_datetime(data["occurred_at"]),
        SubjectRef(**data["subject"]),
        tuple(ActorRef(**actor) for actor in data["actors"]),
        {"notice": row.pk, "snapshot": sha256(snapshot.encode()).hexdigest()},
    )
    validate_event(event)
    if (
        row.kind not in KINDS
        or payload.get("kind") != row.kind
        or event.event_id != row.event_key
        or event.occurred_at != row.created_at
        or event.subject != SubjectRef("moderation-outcome", str(row.pk))
        or payload.get("notice") != row.pk
        or payload.get("recipient") != row.account_id
        or not isinstance(payload.get("applicant_name"), str)
        or not isinstance(payload.get("reason"), str)
        or type(payload.get("shared_reason")) is not bool
        or (not payload["shared_reason"] and payload["reason"])
        or (row.kind != "declined" and (payload["shared_reason"] or payload["reason"]))
    ):
        raise ValueError("Invalid moderation outcome provenance")
    if row.kind != "example":
        submission = payload.get("submission")
        if type(submission) is not int or submission <= 0:
            raise ValueError("Outcome submission provenance required")
        if event.event_id != f"moderation-{submission}-{row.kind}-{row.account_id}":
            raise ValueError("Outcome identity differs from source")
        if (row.kind == "lapsed" and event.actors) or (
            row.kind in {"approved", "declined"} and len(event.actors) != 1
        ):
            raise ValueError("Outcome actor provenance required")
    elif event.actors or not event.event_id.startswith(f"moderation-example-{row.account_id}-"):
        raise ValueError("Invalid synthetic outcome provenance")
    return event


def _matches(event, expected, row):
    return event == StoredEvent(
        **expected.__dict__, recipient_kind="account", recipient_id=row.account_id
    )


def render_payload(payload, *, mode=None):
    """Apply current communication mode without guessing any applicant's alt."""
    kind = payload["kind"]
    if kind == "example":
        return RenderedNotice(
            "Example Moderation outcome: a simulated referral application was approved."
        )
    subject = (
        f"{payload['applicant_name']}'s application"
        if (comms_identity() if mode is None else mode) == "account"
        else "An application using your referral"
    )
    if kind == "approved":
        text = f"{subject} was approved. Their account name and password now work."
    elif kind == "lapsed":
        text = f"{subject} lapsed without approval."
    else:
        detail = (
            f" Reason: {payload['reason']}"
            if payload["shared_reason"] and payload["reason"]
            else ""
        )
        text = f"{subject} was not approved.{detail}"
    return RenderedNotice(text)


class ModerationNoticeSource:
    """Source authority stays with each account's immutable outcome history."""

    label = "Moderation"

    def prepare(self, context):
        """Import a bounded page before an account's login/puppet summary."""
        if authorize_context(context, context.account):
            from evennia_moderation.notices import transfer_pending

            transfer_pending(context.account, context=context)

    def evaluate(self, events, context):
        """Validate owner, provenance and actors before text, counts or compaction."""
        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        from evennia_moderation.models import Notice

        ids = {e.payload.get("notice") for e in events if type(e.payload.get("notice")) is int}
        rows = Notice.objects.filter(pk__in=ids).in_bulk()
        expected, malformed = {}, set()
        actor_ids = {"account": set(), "character": set()}
        for pk, row in rows.items():
            try:
                expected[pk] = event_for(row)
                for actor in expected[pk].actors:
                    actor_ids[actor.kind].add(actor.id)
            except (KeyError, ValueError, TypeError, AttributeError):
                malformed.add(pk)
        actors = {
            "account": set(
                AccountDB.objects.filter(pk__in=actor_ids["account"]).values_list("pk", flat=True)
            ),
            "character": set(
                ObjectDB.objects.filter(pk__in=actor_ids["character"]).values_list("pk", flat=True)
            ),
        }
        outcomes = {}
        for event in events:
            identity = event.payload.get("notice")
            row = rows.get(identity) if type(identity) is int else None
            if (
                row is None
                or event.recipient_kind != "account"
                or event.recipient_id != row.account_id
                or not authorize_context(context)
                or context.account.pk != row.account_id
            ):
                result = Evaluation("invalid")
            elif not row.provenance_known or row.pk in malformed:
                result = Evaluation("defer", reason="provenance")
            elif not _matches(event, expected[row.pk], row):
                result = Evaluation("invalid")
            elif any(actor.id not in actors[actor.kind] for actor in expected[row.pk].actors):
                result = Evaluation("defer", reason="provenance")
            else:
                result = Evaluation("visible")
            outcomes[event.event_id] = result
        return outcomes

    def render(self, events, context):
        """Render only currently eligible historical constituents."""
        if len(events) > 1:
            return RenderedNotice(f"{len(events)} Moderation outcomes. Check your referral alerts.")
        from evennia_moderation.models import Notice

        [event] = events
        if not authorize_context(context):
            raise ValueError("Invalid moderation recipient context")
        row = Notice.objects.get(
            pk=event.payload["notice"], account_id=context.account.pk, provenance_known=True
        )
        if not _matches(event, event_for(row), row):
            raise ValueError("Moderation outcome no longer matches its source")
        return render_payload(row.envelope["payload"])
