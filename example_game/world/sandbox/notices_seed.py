# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Subject-only generic seed and explicit self opt-in notice fixtures."""

import uuid
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
