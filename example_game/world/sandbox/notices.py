# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicitly synthetic reference source; no production source adapters."""

from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.notices import Evaluation, NoticeAction, RenderedNotice

TAG = "notice-demo"
CATEGORY = "sandbox"


class SandboxNoticeSource:
    """Evaluate recipient-owned demo subjects from current underlying state."""

    label = "Sandbox examples"

    def evaluate(self, events, context):
        """Batch subject lookup, owner verification and live deadline/action checks."""
        keys = {e.subject.key for e in events if e.subject and e.subject.kind == "example"}
        subjects = {
            o.db.notice_token: o
            for o in ObjectDB.objects.filter(
                db_tags__db_key=TAG, db_tags__db_category=CATEGORY
            ).distinct()
            if o.db.notice_token in keys
        }
        result = {}
        for event in events:
            subject = subjects.get(event.subject.key) if event.subject else None
            if subject is None:
                outcome = Evaluation("invalid")
            elif (
                subject.db.notice_owner_kind != event.recipient_kind
                or subject.db.notice_owner_id != event.recipient_id
            ):
                outcome = Evaluation("hidden")
            elif event.action_kind and (
                subject.db.notice_state != "offered" or subject.db.notice_deadline <= timezone.now()
            ):
                outcome = Evaluation("invalid")
            elif context.account is None or (
                event.recipient_kind == "character"
                and getattr(context.character, "pk", None) != event.recipient_id
            ):
                outcome = Evaluation("defer", reason="context")
            elif subject.db.notice_state == "hidden":
                outcome = Evaluation("hidden")
            elif subject.db.notice_state == "deferred":
                outcome = Evaluation("defer", reason="context")
            elif event.action_kind and context.account is not None:
                pending = (
                    subject.db.notice_state == "offered"
                    and subject.db.notice_deadline > timezone.now()
                )
                outcome = Evaluation("visible" if pending else "invalid", outstanding=pending)
            else:
                outcome = Evaluation("visible")
            result[event.event_id] = outcome
        return result

    def render(self, events, context):
        """Source text is intentionally labelled and contains no borrowed identities."""
        actions = tuple(
            NoticeAction(
                "Resolve this simulated offer", command=f"+sandbox/notice-confirm {e.subject.key}"
            )
            for e in events
            if e.action_kind
        )
        text = "Example notice: " + (
            f"{len(events)} sandbox activities." if len(events) > 1 else events[0].payload["text"]
        )
        return RenderedNotice(text, actions)
