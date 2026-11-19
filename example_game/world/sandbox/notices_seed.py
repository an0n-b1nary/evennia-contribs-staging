# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Subject-only generic seed and explicit self opt-in notice fixtures."""

import uuid
from collections.abc import Mapping
from datetime import timedelta

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.server.models import ServerConfig
from evennia.utils.create import create_object

from evennia_links.characters import web_roster
from evennia_links.guests import is_guest
from evennia_links.notices import NoticeContext, NoticeEvent, SubjectRef, notify

from .notices import CATEGORY, TAG

PLOT_DEMO_NAME = "Example Plot Inbox"
PLOT_DEMO_REQUESTER_TAG = "example-plot-requester"


def seed_subject_templates(reset=False):
    """Create synthetic templates only; never choose a recipient or emit an alert."""
    generation = ServerConfig.objects.conf("sandbox_notice_generation", default=0)
    if reset or not generation:
        generation += 1
        ServerConfig.objects.conf("sandbox_notice_generation", generation)
    for kind in ("account", "character", "history", "offer"):
        tag = f"notice-template-{kind}"
        if not ObjectDB.objects.filter(db_tags__db_key=tag, db_tags__db_category=CATEGORY).exists():
            subject = create_object(
                "evennia.objects.objects.DefaultObject",
                key=f"Example notice template: {kind}",
                nohome=True,
            )
            subject.tags.add([tag, "sandbox_default"], category=CATEGORY)
            subject.db.notice_template = kind
    return generation


def emit_demo_notices(account, character):
    """Opt in only the supplied account and owned current character, idempotently."""
    if not apps.is_installed("evennia_notices"):
        raise ValueError("The example inbox is unavailable")
    if (
        is_guest(account)
        or not getattr(account, "is_authenticated", False)
        or character not in web_roster(account)
    ):
        raise ValueError("Choose your own playable character before opting in")
    from evennia_notices.models import DeliveryReceipt
    from evennia_notices.services import mutate

    generation = seed_subject_templates()
    context = NoticeContext(account, character)
    results = []
    with transaction.atomic():
        for kind in ("account", "character", "history", "offer"):
            recipient = account if kind == "account" else character
            owner_kind = "account" if kind == "account" else "character"
            identity = f"example-{generation}-{owner_kind}-{recipient.pk}-{kind}"
            matches = ObjectDB.objects.filter(
                db_tags__db_key=identity, db_tags__db_category=CATEGORY
            )
            subject = matches.first()
            if subject is not None and not subject.tags.has(TAG, category=CATEGORY):
                raise ValueError("Example subject identity is not synthetic")
            if subject is None:
                subject = create_object(
                    "evennia.objects.objects.DefaultObject",
                    key=f"Example notice subject: {kind}",
                    nohome=True,
                )
                subject.tags.add([identity, TAG, "sandbox_default"], category=CATEGORY)
                subject.db.notice_token = uuid.uuid4().hex[:12]
                subject.db.notice_owner_kind, subject.db.notice_owner_id = owner_kind, recipient.pk
                subject.db.notice_state = "offered" if kind == "offer" else "visible"
                subject.db.notice_deadline = timezone.now() + timedelta(days=7)
                subject.db.notice_occurred_at = timezone.now()
            event = NoticeEvent(
                identity,
                subject.db.notice_occurred_at,
                subject=SubjectRef("example", subject.db.notice_token),
                payload={
                    "text": "A simulated waitlist place needs your decision."
                    if kind == "offer"
                    else f"Synthetic {kind} activity for exploring the inbox."
                },
                action_kind="waitlist_offer" if kind == "offer" else None,
            )
            result = notify(recipient, source="sandbox-notices", event=event, context=context)
            results.append(result)
            if kind == "history" and result.status == "retained":
                receipt = DeliveryReceipt.objects.get(pk=result.receipt)
                mutate(context, receipt.stored_event.notice.public_ref, "read")
    return results


def resolve_demo_offer(account, character, token, accepted):
    """Recheck synthetic ownership/deadline before resolving this simulated offer."""
    if character not in web_roster(account) or is_guest(account):
        raise ValueError("Choose your own playable character")
    with transaction.atomic():
        matches = ObjectDB.objects.filter(
            db_tags__db_key=TAG, db_tags__db_category=CATEGORY
        ).distinct()
        subject = next((o for o in matches if o.db.notice_token == token), None)
        if (
            subject is None
            or subject.db.notice_owner_kind != "character"
            or subject.db.notice_owner_id != character.pk
        ):
            raise ValueError("Example offer not available")
        # SQLite writer before reading the live state again.
        ObjectDB.objects.filter(pk=subject.pk).update(db_key=subject.key)
        subject.refresh_from_db()
        subject.attributes.reset_cache()
        if subject.db.notice_state in {"confirmed", "declined"}:
            return subject.db.notice_state
        if subject.db.notice_state != "offered" or subject.db.notice_deadline <= timezone.now():
            raise ValueError("Example offer is no longer available")
        subject.db.notice_state = "confirmed" if accepted else "declined"
        return subject.db.notice_state


def emit_calendar_demo_notices(account, character):
    """Explicit self opt-in to real Calendar alerts on labelled synthetic events."""
    if is_guest(account) or character not in web_roster(account):
        raise ValueError("Choose your own playable character before opting in")
    from evennia_calendar import notices as calendar_notices
    from evennia_calendar.models import RSVP, CalendarEvent

    rows = []
    for kind, status in (
        ("selection", RSVP.Status.LOTTERY_SELECTED),
        ("invitation", RSVP.Status.INVITED),
    ):
        event, _ = CalendarEvent.objects.get_or_create(
            creator=character,
            title=f"Example Calendar {kind}",
            defaults={
                "scheduled_time": timezone.now() + timedelta(days=7),
                "description": "Synthetic personal inbox example; no live event or real seat.",
                "participant_cap": 1,
                "is_staff_event": kind == "selection",
            },
        )
        rsvp, _ = RSVP.objects.get_or_create(
            event=event,
            character=character,
            defaults={"status": status, "character_name": character.key},
        )
        if kind == "selection":
            calendar_notices.on_lottery_selected(None, event=event, rsvp=rsvp)
        else:
            calendar_notices.notify(
                rsvp,
                "invited",
                calendar_notices.invited_message(event),
                origin="invitation",
                actor=character,
            )
        rows.append(rsvp)
    return rows


def _lore_demo_content(entry):
    """Snapshot only content/ownership invariants; the server owns provenance."""
    return {
        field: getattr(entry, field)
        for field in (
            "author_id",
            "title",
            "body",
            "summary",
            "kind",
            "accuracy",
            "ooc_notes",
            "sealed_notes",
            "privacy",
            "status",
            "is_archived",
        )
    }


def emit_lore_demo_notices(account, character):
    """Opt in only trusted unchanged synthetic Lore, never title-matched content."""
    from django.db.models import F
    from evennia.accounts.models import AccountDB

    from evennia_lore.models import LoreEntry
    from evennia_lore.notices import transfer_pending

    if is_guest(account) or is_guest(character) or character not in web_roster(account):
        raise ValueError("Choose your own playable character before opting in")
    key = f"sandbox_lore_notice_example_{character.pk}"
    provenance = ServerConfig.objects.conf(key, default=None)
    if provenance is None:
        with transaction.atomic():
            # Serialize first allocation before any provenance/row creation.
            # Only a new, unexposed synthetic entry is mutated under this lock;
            # existing entries are never row-locked or affirmed in this path.
            AccountDB.objects.filter(pk=account.pk).update(username=F("username"))
            AccountDB.objects.select_for_update().get(pk=account.pk)
            provenance = ServerConfig.objects.conf(key, default=None)
            if provenance is None:
                if character not in web_roster(account):
                    raise ValueError("Choose your own playable character before opting in")
                expected = {
                    "author_id": character.pk,
                    "title": f"Example Lore decision: {character.key}",
                    "body": "A labelled synthetic example used only to explore personal notices.",
                    "summary": "",
                    "kind": "fact",
                    "accuracy": "accurate",
                    "ooc_notes": "",
                    "sealed_notes": "",
                    "privacy": LoreEntry.Privacy.PUBLIC.value,
                    "status": LoreEntry.Status.PUBLISHED.value,
                    "is_archived": False,
                }
                if LoreEntry.all_objects.filter(title=expected["title"]).exists():
                    raise ValueError(
                        "That example title is already in use; existing lore was left unchanged"
                    )
                entry = LoreEntry.create_entry(
                    expected["title"],
                    author=character,
                    body=expected["body"],
                    kind="fact",
                    accuracy="accurate",
                    privacy=LoreEntry.Privacy.PUBLIC,
                )
                entry.refresh_from_db()
                if (
                    _lore_demo_content(entry) != expected
                    or entry.affirmation != LoreEntry.Affirmation.NONE
                ):
                    raise ValueError(
                        "The example could not be prepared; your lore was left unchanged"
                    )
                entry.affirm()
                provenance = {"entry": entry.pk, "character": character.pk, "content": expected}
                ServerConfig.objects.conf(key, provenance)
    if (
        not isinstance(provenance, Mapping)
        or type(provenance.get("entry")) is not int
        or provenance.get("character") != character.pk
        or not isinstance(provenance.get("content"), Mapping)
    ):
        raise ValueError("This example is unavailable; your lore was left unchanged")
    entry = LoreEntry.all_objects.filter(pk=provenance["entry"]).first()
    if (
        entry is None
        or entry.author_id != character.pk
        or _lore_demo_content(entry) != provenance["content"]
        or entry.affirmation != LoreEntry.Affirmation.AFFIRMED
        or entry.edited_since_affirmation
    ):
        raise ValueError("The example has changed; lore was left unchanged")
    # Repeats never affirm again, and routing starts after allocation commits.
    transfer_pending(character)
    return entry


def emit_moderation_demo_notices(account, character=None):
    """Opt in the owning account to one simulation, never review real admissions."""
    from django.db.models import F
    from evennia.accounts.models import AccountDB

    from evennia_moderation.integrations.notices import event_for
    from evennia_moderation.models import Notice
    from evennia_moderation.notices import record_example, transfer_pending

    if is_guest(account) or not getattr(account, "is_authenticated", False):
        raise ValueError("Choose an ordinary account before opting in")
    if character is not None and character not in web_roster(account):
        raise ValueError("Choose your own playable character before opting in")
    key = f"sandbox_moderation_notice_example_{account.pk}"
    with transaction.atomic():
        AccountDB.objects.filter(pk=account.pk).update(last_login=F("last_login"))
        AccountDB.objects.select_for_update().get(pk=account.pk)
        marker = ServerConfig.objects.conf(key, default=None)
        if marker is None:
            row = record_example(account, uuid.uuid4().hex)
            row.refresh_from_db(fields=["envelope"])
            marker = {"notice": row.pk, "account": account.pk, "envelope": row.envelope}
            ServerConfig.objects.conf(key, marker)
        if (
            not isinstance(marker, Mapping)
            or type(marker.get("notice")) is not int
            or marker.get("account") != account.pk
            or not isinstance(marker.get("envelope"), Mapping)
        ):
            raise ValueError("The example has changed; admissions were left unchanged")
        row = Notice.objects.filter(pk=marker["notice"]).first()
        if (
            row is None
            or row.account_id != account.pk
            or row.kind != "example"
            or not row.provenance_known
            or row.envelope != marker["envelope"]
        ):
            raise ValueError("The example has changed; admissions were left unchanged")
    event_for(row)  # Refuse malformed synthetic provenance before reporting success.
    transfer_pending(account)
    return row


def emit_social_demo_notice(account, character, *, session=None, golden=False):
    """Allocate one labelled, quietly transferred page for the exact opted-in character."""
    from evennia.comms.models import Msg
    from evennia.server.sessionhandler import SESSIONS
    from evennia.utils.create import create_message

    from evennia_links.notices import authorize_context
    from evennia_social.integrations.notices import GENERATION_TAG, page_actor, page_subjects
    from evennia_social.notices import lock_recipient_owners, record_offline, retry_recorded_page

    def eligible():
        if session is None:
            if not (golden and getattr(account, "pk", None) == 1 and account.is_superuser):
                return False
        elif not any(current is session for current in SESSIONS.get_sessions()):
            return False
        return (
            character is not None
            and not is_guest(character)
            and authorize_context(NoticeContext(account, character, session))
        )

    if not eligible():
        raise ValueError("Choose your own playable character before opting in")

    with transaction.atomic():
        owners = lock_recipient_owners([character])
        if not eligible() or account.pk not in {owner.pk for owner in owners.get(character.pk, ())}:
            raise ValueError("Choose your own playable character before opting in")
        generation = seed_subject_templates()
        marker = f"social-page-{generation}-{character.pk}"
        matches = page_subjects(character.pk).filter(
            db_tags__db_category=CATEGORY, db_tags__db_key=marker
        )
        page = matches.first()
        if page is not None:
            actor = page_actor(page)
            if (
                actor
                and actor.kind == "character"
                and ObjectDB.objects.filter(
                    pk=actor.id,
                    db_tags__db_category=CATEGORY,
                    db_tags__db_key="example-social-page-sender",
                ).exists()
            ):
                retry_recorded_page(character, page.pk)
                return page.pk
            raise ValueError("The example page identity is unavailable")
        if Msg.objects.filter(db_tags__db_category=CATEGORY, db_tags__db_key=marker).exists():
            raise ValueError("The example page identity is unavailable")
        sender = ObjectDB.objects.filter(
            db_tags__db_key="example-social-page-sender", db_tags__db_category=CATEGORY
        ).first()
        if sender is None:
            sender = create_object(
                "evennia.objects.objects.DefaultCharacter",
                key="Example Page Sender",
                nohome=True,
            )
            sender.tags.add(["example-social-page-sender", "sandbox_default"], category=CATEGORY)
        page = create_message(
            sender,
            "[Sandbox example] This simulated page shows how to find offline pages.",
            receivers=[character],
            locks=f"read:id({character.pk})",
            tags=[("page", "comms"), GENERATION_TAG, (marker, CATEGORY)],
        )
        record_offline(page, sender, [character], owners, fresh=False)
        return page.pk


def emit_plot_demo_notice(account, character, *, session=None, golden=False):
    """Open one labelled demonstration request for the exact opted-in character."""
    from django.db.models import F
    from evennia.server.sessionhandler import SESSIONS

    from evennia_links.notices import authorize_context
    from evennia_plots import threads
    from evennia_plots.models import PlotThread

    def eligible():
        return (
            character is not None
            and not is_guest(character)
            and (
                (golden and session is None and account.pk == 1 and account.is_superuser)
                or any(current is session for current in SESSIONS.get_sessions())
            )
            and authorize_context(NoticeContext(account, character, session))
        )

    if not eligible():
        raise ValueError("Choose your own playable character before opting in")

    with transaction.atomic():
        ObjectDB.objects.filter(pk=character.pk).update(db_key=F("db_key"))
        account.attributes.reset_cache()
        if not eligible():
            raise ValueError("Choose your own playable character before opting in")
        generation = seed_subject_templates()
        marker = f"sandbox_plot_notice_{generation}_{character.pk}"
        if ServerConfig.objects.conf(marker, default=None) is not None:
            return
        sender = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Example Plot Requester",
            nohome=True,
        )
        sender.tags.add([PLOT_DEMO_REQUESTER_TAG, "sandbox_default"], category=CATEGORY)
        plot = PlotThread.create_thread(
            PLOT_DEMO_NAME,
            creator=character,
            description="Synthetic example for exploring personal notices.",
            thread_policy=PlotThread.ThreadPolicy.REQUEST,
        )
        plot.activate()
        request = threads.add_thread(
            plot, sender, "Example thread request", "This is a simulated plot thread request."
        )
        plot.privacy = PlotThread.Privacy.PRIVATE
        plot.save(update_fields=["privacy"])
        ServerConfig.objects.conf(marker, request.pk)


def plot_demo_ids():
    """Plots the opt-in example made: its name plus a request from its tagged requester."""
    from evennia_plots.models import PlotThread

    requesters = ObjectDB.objects.filter(
        db_tags__db_key=PLOT_DEMO_REQUESTER_TAG, db_tags__db_category=CATEGORY
    )
    return list(
        PlotThread.objects.filter(name=PLOT_DEMO_NAME, story_threads__created_by__in=requesters)
        .values_list("pk", flat=True)
        .distinct()
    )
