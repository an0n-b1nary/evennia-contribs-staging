# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable source-owned Lore events, optional Inbox routing and safe fallback."""

import logging
import uuid
from dataclasses import asdict

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.module_loading import import_string

from evennia_links.guests import is_guest
from evennia_links.notices import (
    ActorRef,
    NoticeEvent,
    RouteResult,
    StoredEvent,
    SubjectRef,
    authorize_context,
    connected_contexts,
    evaluate,
    normalize_rendered,
    transfer,
)
from evennia_links.notices import (
    notify as route_event,
)

logger = logging.getLogger("evennia")
TERMINAL = {"inbox", "fallback", "suppressed", "invalid"}
KINDS = {"affirmed", "declined", "unsealed"}


def is_online(character):
    """Return whether this character has a connected session."""
    return bool(_sessions(character))


def _sessions(character):
    from evennia.server.sessionhandler import SESSIONS

    return [session for session in SESSIONS.get_sessions() if session.get_puppet() == character]


def _guest_session_owned(session, character):
    from evennia.accounts.models import AccountDB

    from evennia_links.characters import account_ids

    account = session.get_account()
    return (
        isinstance(account, AccountDB)
        and bool(account.pk)
        and AccountDB.objects.filter(pk=account.pk).exists()
        and session.get_puppet() == character
        and (account.pk in account_ids(character) or character.account == account)
    )


def _actor_policy(account, actors):
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from evennia_links.ignoring import notice_ignore_status

    for ref in actors:
        model = {"account": AccountDB, "character": ObjectDB}.get(ref["kind"])
        actor = model.objects.filter(pk=ref["id"]).first() if model else None
        if actor is None:
            return "defer"
        status = notice_ignore_status(account, actor)
        if status != "allow":
            return status
    return "allow"


def _advisory_text(payload):
    """Refresh advisory constituents without turning the review workflow into Inbox."""
    from django.apps import apps

    from evennia_lore.models import LoreEntry

    label = getattr(settings, "LORE_PLOTS_APP_LABEL", "evennia_plots")
    try:
        model = apps.get_model(label, "PlotThread")
    except LookupError:
        return None
    thread = model.objects.filter(pk=payload.get("thread")).first()
    if thread is None:
        return None
    if getattr(
        thread, "status", None
    ) != "concluded" or thread.concluded_at.isoformat() != payload.get("concluded_at"):
        return None
    if payload.get("origin") == "creator" and thread.creator_id != payload["recipient"]:
        return None
    entries = list(
        LoreEntry.objects.filter(pk__in=payload["entries"], plot_links__thread_id=thread.pk)
        .exclude(sealed_notes="")
        .order_by("entry_number")
    )
    if not entries:
        return None
    numbers = ", ".join(f"#{entry.entry_number}" for entry in entries)
    return f"[Lore] Linked lore still sealed: {numbers}. Staff can unseal with +lore/unseal <id>=<accuracy>."


def _render(row):
    from .integrations.notices import render_payload

    if row.kind == "advisory":
        return _advisory_text(row.envelope["payload"])
    return normalize_rendered(render_payload(row.envelope["payload"])).text


def _allowed(row, context):
    from .integrations.notices import LoreNoticeSource, event_for

    if row.kind == "advisory":
        if context.character != row.character or not authorize_context(context, row.character):
            return "defer"
        if _advisory_text(row.envelope["payload"]) is None:
            return "invalid"
        policy = _actor_policy(context.account, row.envelope["actors"])
        return "visible" if policy == "allow" else "hidden" if policy == "suppress" else "defer"
    event = StoredEvent(
        **event_for(row).__dict__, recipient_kind="character", recipient_id=row.character_id
    )
    return evaluate(LoreNoticeSource(), [event], context)[event.event_id].status


def _guest_notify(character, payload, actors, key):
    """Send only to live owned guest sessions; persist no source or Inbox record."""
    from evennia.objects.models import ObjectDB

    from .integrations.notices import render_payload, subject_status
    from .models import LoreEntry

    delivered = False
    for session in _sessions(character):
        live = ObjectDB.objects.filter(pk=character.pk).first()
        if live is None or not _guest_session_owned(session, live):
            continue
        if _actor_policy(session.get_account(), actors) != "allow":
            continue
        if payload["kind"] == "advisory":
            text = _advisory_text(payload)
        else:
            entry = LoreEntry.all_objects.filter(pk=payload["entry"]).first()
            if subject_status(entry, live, payload).status != "visible":
                continue
            text = normalize_rendered(render_payload(payload)).text
        if text is None or not _guest_session_owned(session, live):
            continue
        seen = getattr(session, "_lore_notice_attempts", set())
        if key in seen:
            continue
        session._lore_notice_attempts = seen | {key}
        try:
            session.msg(text)
            delivered = True
        except Exception:
            logger.warning("Lore guest delivery uncertain; transient claim retained")
    return delivered


def _safe_guest(character, payload, actors, key):
    try:
        return _guest_notify(character, payload, actors, key)
    except Exception:
        logger.warning("Lore guest delivery deferred", exc_info=True)
        return False


def notify(character, message, entry=None, *, kind=None, actor=None, advisory=None):
    """Record a typed decision, preserving the positional custom-call interface.

    Untyped custom calls remain held history. Only explicit source provenance
    permits disclosure. The return value is True only for completed fallback.
    """
    from .models import LoreNotice

    if character is None:
        return False
    if entry is not None and getattr(entry, "_notice_duplicate", False):
        return False
    known = kind in KINDS or (kind == "advisory" and advisory is not None)
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    if actor is not None and (not isinstance(actor, AccountDB | ObjectDB) or not actor.pk):
        raise ValueError("Lore notice actor must be a saved account or character")
    actors = (
        [{"kind": "account" if isinstance(actor, AccountDB) else "character", "id": actor.pk}]
        if actor is not None
        else []
    )
    key = (
        f"lore-{entry.pk}-{entry.notice_sequence}-{kind}-{character.pk}"
        if entry is not None and known
        else f"lore-{uuid.uuid4().hex}"
    )
    payload = {"kind": kind or "unknown", "recipient": character.pk}
    if entry is not None:
        payload.update(
            entry=entry.pk,
            author=entry.author_id,
            title=entry.title,
            number=entry.entry_number,
            note=entry.affirmation_note if kind == "declined" else "",
        )
    if advisory is not None:
        payload.update(advisory)
        key = f"lore-advisory-{payload['thread']}-{payload['concluded_at']}-{character.pk}"
    if is_guest(character):
        if not known:
            return False
        results = []
        transaction.on_commit(lambda: results.append(_safe_guest(character, payload, actors, key)))
        return bool(results and results[0])
    with transaction.atomic():
        row, created = LoreNotice.objects.get_or_create(
            event_key=key,
            defaults={
                "character": character,
                "entry": entry,
                "message": message,
                "kind": kind or "unknown",
                "provenance_known": known,
            },
        )
        if created and known:
            payload["notice"] = row.pk
            event = NoticeEvent(
                key,
                row.created_at,
                subject=SubjectRef(
                    "lore" if entry else "lore-advisory",
                    str(entry.pk if entry else payload["thread"]),
                ),
                actors=tuple(ActorRef(**ref) for ref in actors),
                payload=payload,
            )
            row.envelope = asdict(event)
            row.envelope["occurred_at"] = event.occurred_at.isoformat()
            row.save(update_fields=["envelope"])
        if known:
            transaction.on_commit(lambda: _safe_route(row.pk, fresh=True))
    row.refresh_from_db()
    return row.route_state == "fallback"


def _safe_route(pk, fresh=False):
    try:
        return route_notice(pk, fresh=fresh)
    except Exception:
        logger.warning("Lore notice routing deferred", exc_info=True)
        return "retry"


def _ack(row, state):
    row.route_state = state
    row.acknowledged_at = timezone.now() if state in TERMINAL else None
    row.save(update_fields=["route_state", "acknowledged_at"])


def route_notice(pk, *, fresh=False, context=None):
    """Route one source event under a single lock, retaining uncertainty."""
    from .integrations.notices import event_for
    from .models import LoreEntry, LoreNotice

    candidate = LoreNotice.objects.get(pk=pk)
    with transaction.atomic():
        if candidate.entry_id:
            LoreEntry.all_objects.filter(pk=candidate.entry_id).update(
                notice_sequence=F("notice_sequence")
            )
            LoreEntry.all_objects.select_for_update().get(pk=candidate.entry_id)
        LoreNotice.objects.filter(pk=pk).update(route_state=F("route_state"))
        row = LoreNotice.objects.select_for_update().get(pk=pk)
        if row.route_state != "pending":
            return row.route_state
        if not row.provenance_known or not row.envelope:
            return "held"
        if is_guest(row.character):
            # Existing structured guest history is acknowledged once, never copied.
            sessions = _sessions(row.character)
            if not sessions:
                return "pending"
            row.route_state = "attempting"
            row.save(update_fields=["route_state"])
            guest = True
        else:
            guest = False
            try:
                registry = getattr(settings, "LINKS_NOTICE_SOURCES", {})
                if not isinstance(registry, dict):
                    return "retry"
                # Resolve all configured entries to distinguish broken policy from absence.
                from evennia_links.notices import source_registry

                source_registry()
                if row.kind == "advisory" or "lore" not in registry:
                    result = RouteResult("fallback_pending")
                else:
                    with transaction.atomic():
                        result = (route_event if fresh else transfer)(
                            row.character,
                            source="lore",
                            event=event_for(row),
                            context=context,
                            fallback=lambda *args: RouteResult("fallback_pending"),
                            **({} if fresh else {"transfer_id": f"lore-transfer-{row.event_key}"}),
                        )
                        if result.status in {"retained", "duplicate", "suppressed"}:
                            _ack(row, "suppressed" if result.status == "suppressed" else "inbox")
                            return row.route_state
                        if result.status != "fallback_pending":
                            raise RuntimeError("Routing not acknowledged")
            except Exception:
                return "retry"
            contexts = list(connected_contexts(row.character))
            if context is not None and context.session is not None:
                contexts = [context] if authorize_context(context, row.character) else []
            if not contexts:
                return "pending"
            statuses = [_allowed(row, current) for current in contexts]
            if all(status in {"invalid", "hidden"} for status in statuses):
                _ack(row, "invalid" if "invalid" in statuses else "suppressed")
                return row.route_state
            if "visible" not in statuses:
                return "held"
            row.route_state = "attempting"
            row.save(update_fields=["route_state"])
    if connection.in_atomic_block:
        transaction.on_commit(lambda: _deliver_claim(pk, contexts if not guest else [], guest))
        return "attempting"
    return _deliver_claim(pk, contexts if not guest else [], guest)


def _deliver_claim(pk, contexts, guest):
    """Only run socket I/O after the durable attempt transaction commits."""
    from .models import LoreNotice

    row = LoreNotice.objects.get(pk=pk)
    # Socket I/O is after the durable attempting claim commits.
    delivered = False
    try:
        row.refresh_from_db()
        if guest:
            delivered = _guest_notify(
                row.character, row.envelope["payload"], row.envelope["actors"], row.event_key
            )
        else:
            for current in contexts:
                row.refresh_from_db()
                if (
                    not authorize_context(current, row.character)
                    or _allowed(row, current) != "visible"
                ):
                    continue
                text = _render(row)
                if text is not None and authorize_context(current, row.character):
                    current.session.msg(text)
                    delivered = True
    except Exception:
        logger.warning("Lore delivery uncertain; source attempt retained")
    _ack(row, "fallback" if delivered else "uncertain")
    return row.route_state


def transfer_pending(character=None, *, context=None, limit=None):
    """Process a bounded page, advancing past held work without starving new events."""
    from .models import LoreNotice, LoreNoticeCursor

    limit = getattr(settings, "LORE_NOTICE_TRANSFER_BATCH", 100) if limit is None else limit
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Lore transfer limit must be 1 through 1000")
    query = LoreNotice.objects.filter(route_state="pending").order_by("pk")
    if character is not None:
        query = query.filter(character=character)
    guest = character is not None and is_guest(character)
    scope = f"character-{character.pk}" if character is not None else "all"
    cursor = None if guest else LoreNoticeCursor.objects.get_or_create(scope=scope)[0]
    last = getattr(character.ndb, "lore_transfer_position", 0) or 0 if guest else cursor.last_pk
    ids = list(query.filter(pk__gt=last).values_list("pk", flat=True)[:limit])
    if not ids and last:
        ids = list(query.values_list("pk", flat=True)[:limit])
    counts = {
        name: 0
        for name in (
            "inbox",
            "fallback",
            "suppressed",
            "invalid",
            "held",
            "retry",
            "pending",
            "uncertain",
            "attempting",
        )
    }
    for pk in ids:
        # Global cursor must never create a separate guest cursor.
        outcome = _safe_route(pk) if context is None else route_notice(pk, context=context)
        counts[outcome] = counts.get(outcome, 0) + 1
    if ids:
        if guest:
            character.ndb.lore_transfer_position = ids[-1]
        else:
            cursor.last_pk = ids[-1]
            cursor.save(update_fields=["last_pk"])
    counts["continuation"] = query.filter(pk__gt=ids[-1] if ids else last).count()
    return counts


def deliver_pending(character):
    """Route one bounded pending page; return completed standalone deliveries."""
    return transfer_pending(character)["fallback"]


def _on_post_puppet(sender, session=None, **kwargs):
    try:
        context = None
        if session is not None:
            from evennia_links.notices import session_context

            context = session_context(session)
        transfer_pending(sender, context=context)
    except Exception:
        logger.warning("Lore pending transfer deferred; puppet continues", exc_info=True)


def connect():
    """Register without querying source tables during app startup."""
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    SIGNAL_OBJECT_POST_PUPPET.connect(_on_post_puppet, dispatch_uid="evennia_lore.notices")


def file_staff_review(title, description):
    """Pass a staff-review item to LORE_STAFF_REVIEW_HOOK, if one is set.

    Errors are logged, never raised: the lore action that prompted the review
    has already happened and must not be undone by a failed ticket.

    Returns:
        bool: True if the hook ran without error.
    """
    path = getattr(settings, "LORE_STAFF_REVIEW_HOOK", None)
    if not path:
        return False
    try:
        hook = import_string(path) if isinstance(path, str) else path
        hook(title, description)
    except Exception:
        logger.exception("evennia_lore.notices: LORE_STAFF_REVIEW_HOOK failed for %r", title)
        return False
    return True
