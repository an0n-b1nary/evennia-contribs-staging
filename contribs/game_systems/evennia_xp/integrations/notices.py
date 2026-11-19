# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Inbox projection of the current ledger for one selected recipient."""

from django.db.models import Exists, OuterRef
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.characters import playable_accounts
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

from ..models import XPLog, XPNoticeReceipt
from ..notices import State, owner_ids, prepare_character
from ..summary import grouped_totals, summary_text


def event_for(row, character_id):
    """Stable identity and timestamp. Totals and presentation come from the ledger."""
    return NoticeEvent(
        f"xp-{character_id}-{row.week}",
        row.occurred_at,
        SubjectRef("xp-week", row.week),
    )


def _week(event):
    if (
        event.recipient_kind == "character"
        and type(event.recipient_id) is int
        and isinstance(event.subject, SubjectRef)
        and event.subject.kind == "xp-week"
        and isinstance(event.subject.key, str)
        and 0 < len(event.subject.key) <= 10
    ):
        return event.subject.key


def _projection(events, context):
    outcomes = {event.event_id: Evaluation("invalid") for event in events}
    visible = set()
    if not isinstance(context, NoticeContext):
        return outcomes, visible
    account, character = context.account, context.character
    if account is not None and (
        not isinstance(account, AccountDB) or not account.pk or is_guest(account)
    ):
        return outcomes, visible
    if character is None:
        if account is not None:
            roster = {
                member.pk
                for _, characters in playable_accounts(AccountDB.objects.filter(pk=account.pk))
                for member in characters
            }
            for event in events:
                if _week(event) is not None and event.recipient_id in roster:
                    outcomes[event.event_id] = Evaluation("defer", reason="context")
        return outcomes, visible
    if not isinstance(character, ObjectDB) or is_guest(character):
        return outcomes, visible
    owners = owner_ids(character)
    if not owners or (
        account is not None
        and (
            account.pk not in owners
            or (
                context.session is not None
                and (
                    context.session.get_account() != account
                    or context.session.get_puppet() != character
                )
            )
        )
    ):
        return outcomes, visible

    scoped = []
    for event in events:
        week = _week(event)
        if week is not None and event.recipient_id == character.pk:
            scoped.append((event, week))
    if not scoped:
        return outcomes, visible
    rows = {
        row.week: row
        for row in XPNoticeReceipt.objects.filter(
            summary__character_id=character.pk,
            week__in={week for _, week in scoped},
            state__in=(State.PENDING, State.TRANSFERRED),
        ).filter(Exists(XPLog.objects.filter(character_id=character.pk, week=OuterRef("week"))))
    }
    for event, week in scoped:
        row = rows.get(week)
        if row is None:
            continue
        expected = StoredEvent(
            **vars(event_for(row, character.pk)),
            recipient_kind="character",
            recipient_id=character.pk,
        )
        if event == expected:
            if account is None:
                outcomes[event.event_id] = Evaluation("defer", reason="context")
            else:
                outcomes[event.event_id] = Evaluation("visible")
                visible.add(week)
    return outcomes, visible


class XPNoticeSource:
    label = "XP"

    def prepare(self, context):
        if (
            isinstance(context, NoticeContext)
            and isinstance(context.character, ObjectDB)
            and isinstance(context.account, AccountDB)
            and context.session is not None
        ):
            prepare_character(context.character, context=context)

    def evaluate(self, events, context):
        outcomes, _ = _projection(events, context)
        return outcomes

    def render(self, events, context):
        _, visible = _projection(events, context)
        if not visible:
            raise ValueError("No current XP payout to render")
        if len(visible) == 1:
            week = next(iter(visible))
            totals = grouped_totals(context.character.pk, [week]).get(week)
            if not totals:
                raise ValueError("XP payout no longer exists")
            text = summary_text(week, totals, plain=True)
        else:
            text = "XP was awarded for multiple weeks. Use +xp to view your balance and history."
        return normalize_rendered(RenderedNotice(text))
