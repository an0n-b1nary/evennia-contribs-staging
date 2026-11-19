# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Current visibility and fixed presentation of Social page alerts."""

from django.db.models import Count, Exists, F, Min, OuterRef
from evennia.comms.models import Msg

from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeAction,
    NoticeEvent,
    RenderedNotice,
    StoredEvent,
    SubjectRef,
    authorize_context,
)

from ..models import PageDelivery

SOURCE = "social-pages"
GENERATION_TAG = ("v1", "social-page-generation")
PAGE_TAG = {"db_tags__db_key__iexact": "page", "db_tags__db_category__iexact": "comms"}


def event_for(row):
    return NoticeEvent(
        f"social-page-{row.character_id}-{row.message_id}",
        row.occurred_at,
        SubjectRef("social-page", str(row.message_id)),
        (ActorRef(row.actor_kind, row.actor_id),),
        {"character": row.character_id},
    )


def stored_event(row):
    return StoredEvent(
        **vars(event_for(row)), recipient_kind="character", recipient_id=row.character_id
    )


def page_subjects(character_id):
    """Load only identity and lock data, with exact receiver and hide relations."""
    tagged = Msg.objects.filter(pk=OuterRef("pk"), **PAGE_TAG)
    hidden = Msg.objects.filter(pk=OuterRef("pk"), db_hide_from_objects=character_id)
    generated = Msg.objects.filter(
        pk=OuterRef("pk"),
        db_tags__db_key=GENERATION_TAG[0],
        db_tags__db_category=GENERATION_TAG[1],
    )
    scripts = Msg.objects.filter(pk=OuterRef("pk"), db_sender_scripts__isnull=False)
    return (
        Msg.objects.filter(db_receivers_objects=character_id)
        .filter(Exists(tagged), ~Exists(hidden))
        .annotate(
            generated=Exists(generated),
            has_script_sender=Exists(scripts),
            subject_date=F("db_date_created"),
            subject_lock=F("db_lock_storage"),
            external_sender=F("db_sender_external"),
            account_sender_count=Count("db_sender_accounts", distinct=True),
            object_sender_count=Count("db_sender_objects", distinct=True),
            account_sender=Min("db_sender_accounts"),
            object_sender=Min("db_sender_objects"),
        )
        .only("id", "db_date_created", "db_lock_storage", "db_sender_external")
    )


def page_actor(page):
    if page.external_sender or page.has_script_sender:
        return None
    if page.account_sender_count == 1 and not page.object_sender_count:
        return ActorRef("account", page.account_sender)
    if page.object_sender_count == 1 and not page.account_sender_count:
        return ActorRef("character", page.object_sender)
    return None


def subject_status(row, page, character):
    if page is None:
        return "hidden"
    if not page.locks.check_lockstring(
        character, page.subject_lock, access_type="read", default=False, no_superuser_bypass=True
    ):
        return "hidden"
    actor = page_actor(page)
    if (
        actor is None
        or actor != ActorRef(row.actor_kind, row.actor_id)
        or page.subject_date != row.occurred_at
    ):
        return "invalid"
    return "visible"


class SocialPageNoticeSource:
    label = "Social pages"

    def prepare(self, context):
        from ..notices import prepare

        prepare(context, allow_fallback=True)

    def evaluate(self, events, context):
        outcomes = {event.event_id: Evaluation("invalid") for event in events}
        by_recipient = {}
        for event in events:
            if (
                event.recipient_kind == "character"
                and type(event.recipient_id) is int
                and isinstance(event.payload, dict)
                and type(event.payload.get("character")) is int
                and event.subject is not None
                and event.subject.kind == "social-page"
                and isinstance(event.subject.key, str)
                and event.subject.key.isascii()
                and event.subject.key.isdecimal()
                and len(event.subject.key) <= 19
            ):
                by_recipient.setdefault(event.recipient_id, []).append(event)
        for character_id, candidates in by_recipient.items():
            ids = [int(event.subject.key) for event in candidates]
            rows = {
                row.message_id: row
                for row in PageDelivery.objects.filter(
                    character_id=character_id, message_id__in=ids
                )
                .exclude(origin=PageDelivery.Origin.LIVE)
                .filter(state__in=(PageDelivery.State.PENDING, PageDelivery.State.INBOX))
                .select_related("character")
            }
            pages = {page.pk: page for page in page_subjects(character_id).filter(pk__in=rows)}
            exact = getattr(context.character, "pk", None) == character_id and authorize_context(
                context
            )
            for event in candidates:
                row = rows.get(int(event.subject.key))
                if row is None or stored_event(row) != event:
                    continue
                status = subject_status(row, pages.get(row.message_id), row.character)
                if status != "visible":
                    outcomes[event.event_id] = Evaluation(status)
                elif getattr(context.account, "pk", None) in row.suppressed_owners:
                    outcomes[event.event_id] = Evaluation("hidden")
                elif exact:
                    outcomes[event.event_id] = Evaluation("visible")
                else:
                    outcomes[event.event_id] = Evaluation("defer", reason="context")
        return outcomes

    def render(self, events, context):
        text = (
            "You received a page while offline."
            if len(events) == 1
            else "You received pages while offline."
        )
        return RenderedNotice(text, (NoticeAction("View pages", command="page/last"),))
