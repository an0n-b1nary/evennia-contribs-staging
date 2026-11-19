# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Current character and plot visibility for RP Resources notices."""

from django.db.models import Exists, OuterRef, Q
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

from ..models import ResourceNoticeReceipt
from ..notices import (
    State,
    award_text,
    can_view_plot,
    grouped_gains,
    live_connection,
    owner_ids,
    plots_model,
    prepare_character,
    valid_award,
)

WEEKLY = "resource-weekly"
PLOT = "resource-plot"


def event_for(row):
    """Use the immutable award kind, witness ID, and actual award time."""
    if row.weekly_id is not None:
        kind, key, occurred_at = WEEKLY, row.weekly_id, row.weekly.created
    else:
        kind, key, occurred_at = PLOT, row.plot_id, row.plot.paid_at
    return NoticeEvent(f"{kind}-{key}", occurred_at, SubjectRef(kind, str(key)))


def _subject(event):
    if (
        event.recipient_kind == "character"
        and type(event.recipient_id) is int
        and event.recipient_id > 0
        and isinstance(event.subject, SubjectRef)
        and event.subject.kind in (WEEKLY, PLOT)
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


def _rows(scoped, character):
    subjects = {event.subject for event in scoped}
    return {
        (WEEKLY, row.weekly_id) if row.weekly_id else (PLOT, row.plot_id): row
        for row in ResourceNoticeReceipt.objects.filter(
            Q(weekly_id__in={int(s.key) for s in subjects if s.kind == WEEKLY})
            | Q(plot_id__in={int(s.key) for s in subjects if s.kind == PLOT}),
            character_id=character.pk,
            state__in=(State.PENDING, State.TRANSFERRED),
        ).select_related("weekly", "plot__run")
    }


def _plots(rows, character):
    ids = {row.plot.run.thread_id for row in rows if row.plot_id}
    if not ids:
        return {}
    model = plots_model()
    if model is None:
        return None
    return (
        model.objects.filter(pk__in=ids)
        .annotate(
            resources_owner=Exists(
                model.owners.rel.related_model.objects.filter(
                    plot_id=OuterRef("pk"), character_id=character.pk
                )
            )
        )
        .in_bulk()
    )


def _projection(events, context):
    invalid = Evaluation("invalid")
    deferred = Evaluation("defer", reason="context")
    outcomes = {event.event_id: deferred if _subject(event) else invalid for event in events}
    visible = []
    if not isinstance(context, NoticeContext) or not isinstance(context.character, ObjectDB):
        return outcomes, visible
    account, character = context.account, context.character
    if account is not None and (
        not isinstance(account, AccountDB)
        or is_guest(account)
        or account.pk not in owner_ids(character)
    ):
        return outcomes, visible
    if is_guest(character) or not _current(context):
        return outcomes, visible

    scoped = [event for event in events if _subject(event) and event.recipient_id == character.pk]
    if not scoped:
        return outcomes, visible
    rows = _rows(scoped, character)
    revealed = get("RP_RESOURCES_REVEALED")
    plots = _plots(rows.values(), character) if revealed else {}
    for event in scoped:
        subject = event.subject
        row = rows.get((subject.kind, int(subject.key)))
        if (
            row is None
            or not valid_award(row)
            or event
            != StoredEvent(
                **vars(event_for(row)), recipient_kind="character", recipient_id=character.pk
            )
        ):
            outcomes[event.event_id] = invalid
            continue
        if not revealed or (row.plot_id and plots is None):
            outcomes[event.event_id] = Evaluation("defer", reason="unavailable")
            continue
        plot = None
        if row.plot_id is not None:
            plot = plots.get(row.plot.run.thread_id)
            if plot is None:
                outcomes[event.event_id] = invalid
                continue
            current = context if context.session is not None else None
            if not can_view_plot(plot, character, current, owner=plot.resources_owner):
                continue
        if account is not None and _current(context):
            outcomes[event.event_id] = Evaluation("visible")
            visible.append((row, plot))
    return outcomes, visible


class ResourcesNoticeSource:
    """Expose committed character-owned resource awards to the optional Inbox."""

    label = "RP Resources"

    def prepare(self, context):
        """Import pending awards before the Inbox's puppet summary."""
        if (
            isinstance(context, NoticeContext)
            and isinstance(context.character, ObjectDB)
            and isinstance(context.account, AccountDB)
            and context.session is not None
        ):
            prepare_character(context.character, context=context)

    def evaluate(self, events, context):
        """Recheck award validity and current viewer access."""
        return _projection(events, context)[0]

    def render(self, events, context):
        """Render a current award or a privacy-safe compacted summary."""
        _, visible = _projection(events, context)
        if not visible:
            raise ValueError("No current Resources award to render")
        if len(visible) > 1:
            text = "You received resource awards. Use +resources to view your stores."
        else:
            row, plot = visible[0]
            gains = (
                grouped_gains(context.character, [row.weekly.week]).get(row.weekly.week, ())
                if row.weekly_id is not None
                else ()
            )
            text = award_text(row, gains=gains, plot=plot, inbox=True)
        rendered = normalize_rendered(RenderedNotice(text))
        _, current = _projection(events, context)
        if not current:
            raise ValueError("Resources award is no longer available")
        if len(visible) == 1:
            current_row, current_plot = current[0]
            if (
                len(current) != 1
                or current_row.pk != row.pk
                or (
                    current_plot is not None
                    and (current_plot.name != plot.name or current_plot.privacy != plot.privacy)
                )
            ):
                raise ValueError("Resources award changed during rendering")
        return rendered
