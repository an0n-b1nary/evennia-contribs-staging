# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Current character visibility for Economy income and stipend notices."""

from django.db.models import Q
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.guests import is_guest
from evennia_links.notices import (
    Evaluation,
    NoticeContext,
    NoticeEvent,
    RenderedNotice,
    StoredEvent,
    SubjectRef,
    normalize_rendered,
)
from evennia_links.runtime import get

from ..models import EconomyNoticeReceipt
from ..notices import (
    State,
    live_connection,
    owner_ids,
    payment_text,
    prepare_character,
    valid_payment,
)

INCOME = "economy-income"
STIPEND = "economy-stipend"


def event_for(row):
    """Use the immutable payment kind, payment ID, and actual payment time."""
    if row.ubi_id is not None:
        kind, key, occurred_at = INCOME, row.ubi_id, row.ubi.created
    else:
        kind, key, occurred_at = STIPEND, row.stipend_id, row.stipend.created
    return NoticeEvent(f"{kind}-{key}", occurred_at, SubjectRef(kind, str(key)))


def _subject(event):
    if (
        event.recipient_kind == "character"
        and type(event.recipient_id) is int
        and event.recipient_id > 0
        and isinstance(event.subject, SubjectRef)
        and event.subject.kind in (INCOME, STIPEND)
        and isinstance(event.subject.key, str)
        and 0 < len(event.subject.key) <= 19
        and event.subject.key.isascii()
        and event.subject.key.isdecimal()
        and 0 < int(event.subject.key) < 2**63
        and not event.subject.key.startswith("0")
    ):
        return event.subject


def _current(context):
    return context.session is None or (context.account is not None and live_connection(context))


def _current_viewer(context):
    account, character = context.account, context.character
    return (
        (
            account is None
            or (
                isinstance(account, AccountDB)
                and not is_guest(account)
                and account.pk in owner_ids(character)
            )
        )
        and not is_guest(character)
        and _current(context)
    )


def _rows(scoped, character):
    subjects = {event.subject for event in scoped}
    return {
        (INCOME, row.ubi_id) if row.ubi_id else (STIPEND, row.stipend_id): row
        for row in EconomyNoticeReceipt.objects.filter(
            Q(ubi_id__in={int(s.key) for s in subjects if s.kind == INCOME})
            | Q(stipend_id__in={int(s.key) for s in subjects if s.kind == STIPEND}),
            character_id=character.pk,
            state__in=(State.PENDING, State.TRANSFERRED),
        ).select_related("ubi", "stipend")
    }


def _projection(events, context):
    invalid = Evaluation("invalid")
    deferred = Evaluation("defer", reason="context")
    outcomes = {event.event_id: deferred if _subject(event) else invalid for event in events}
    visible = []
    if not isinstance(context, NoticeContext) or not isinstance(context.character, ObjectDB):
        return outcomes, visible
    if not _current_viewer(context):
        return outcomes, visible

    account, character = context.account, context.character
    scoped = [event for event in events if _subject(event) and event.recipient_id == character.pk]
    if not scoped:
        return outcomes, visible
    rows = _rows(scoped, character)
    # Never conf.visible: dark accrual is hidden from staff as well.
    revealed = get("RP_ECONOMY_REVEALED")
    for event in scoped:
        subject = event.subject
        row = rows.get((subject.kind, int(subject.key)))
        if (
            row is None
            or not valid_payment(row)
            or event
            != StoredEvent(
                **vars(event_for(row)), recipient_kind="character", recipient_id=character.pk
            )
        ):
            outcomes[event.event_id] = invalid
            continue
        if not revealed:
            outcomes[event.event_id] = Evaluation("defer", reason="unavailable")
            continue
        if account is not None:
            visible.append((event.event_id, row))

    if not visible:
        return outcomes, []
    if not get("RP_ECONOMY_REVEALED"):
        for event_id, _ in visible:
            outcomes[event_id] = Evaluation("defer", reason="unavailable")
        return outcomes, []
    if not _current_viewer(context):
        return outcomes, []
    for event_id, _ in visible:
        outcomes[event_id] = Evaluation("visible")
    return outcomes, [row for _, row in visible]


class EconomyNoticeSource:
    """Expose committed character-owned income and stipends to the optional Inbox."""

    label = "Economy"

    def prepare(self, context):
        """Import pending payments before the Inbox's puppet summary."""
        if (
            isinstance(context, NoticeContext)
            and isinstance(context.character, ObjectDB)
            and isinstance(context.account, AccountDB)
            and context.session is not None
        ):
            prepare_character(context.character, context=context)

    def evaluate(self, events, context):
        """Recheck payment validity, the reveal and current viewer access."""
        return _projection(events, context)[0]

    def render(self, events, context):
        """Render a current payment or a privacy-safe compacted summary."""
        _, visible = _projection(events, context)
        if not visible:
            raise ValueError("No current Economy payment to render")
        if len(visible) > 1:
            text = "You received income or stipends. See +balance."
        else:
            text = payment_text(visible[0])
        rendered = normalize_rendered(RenderedNotice(text))
        _, current = _projection(events, context)
        if not current:
            raise ValueError("Economy payment is no longer available")
        if [row.pk for row in current] != [row.pk for row in visible] or (
            len(current) == 1 and payment_text(current[0]) != text
        ):
            raise ValueError("Economy payment changed during rendering")
        return rendered
