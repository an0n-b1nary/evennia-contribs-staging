# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Calendar source queue, immutable events and exactly one chosen delivery path.

Source-owned receipts survive inbox removal. Unknown legacy human authors and
ambiguous pre-upgrade generations remain pending without text or counts.
"""

import logging
from dataclasses import asdict

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from evennia_links.characters import account_ids
from evennia_links.guests import is_guest
from evennia_links.notices import (
    ActorRef,
    NoticeContext,
    NoticeEvent,
    StoredEvent,
    SubjectRef,
    authorize_context,
    evaluate,
    normalize_rendered,
    source_registry,
    transfer,
)
from evennia_links.notices import (
    notify as route_new_event,
)

logger = logging.getLogger("evennia")
TIME_FORMAT = "%Y-%m-%d %H:%M"
TERMINAL = {"inbox", "fallback", "suppressed", "invalid"}
SYSTEM_ORIGINS = {"drawn": "lottery", "seated": "seated", "reminder": "reminder"}


def is_online(character):
    """Return whether a character has any actual connected sessions."""
    try:
        return bool(character.sessions.count())
    except Exception:
        return False


def _connected_sessions(character):
    return list(character.sessions.all()) if is_online(character) else []


def _actor_refs(actor):
    if actor is None:
        return []
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    if isinstance(actor, AccountDB) and actor.pk:
        return [asdict(ActorRef("account", actor.pk))]
    if isinstance(actor, ObjectDB) and actor.pk:
        return [asdict(ActorRef("character", actor.pk))]
    raise ValueError("Calendar notice actor must be a saved character or account")


def _system_transition_rows(rsvp, character_id, kind, status, actors, origin):
    """Compatible source records for one provably current system transition."""
    from .models import CalendarNotice

    if (
        origin != SYSTEM_ORIGINS.get(kind)
        or status != rsvp.status
        or character_id != rsvp.character_id
    ):
        return CalendarNotice.objects.none()
    return (
        CalendarNotice.objects.filter(
            rsvp_id=rsvp.pk,
            character_id=character_id,
            kind=kind,
            status=status,
            actors=actors,
        )
        .filter(
            Q(generation=rsvp.notice_generation, provenance_known=True, origin=origin)
            | Q(event_key__isnull=True, generation__isnull=True, created_at__gte=rsvp.updated_at)
        )
        .order_by("pk")
    )


def _freeze(row):
    """Choose/freeze one canonical source row independently of routing order.

    The caller holds the RSVP writer lock. Pending legacy system duplicates
    and their current producer callback share the earliest compatible source
    row, including a source row already consumed by standalone delivery.
    """
    if row.envelope:
        canonical_id = row.envelope["payload"]["notice"]
        if canonical_id == row.pk:
            return row
        canonical = (
            type(row)
            .objects.select_for_update()
            .select_related("rsvp__event", "character")
            .get(pk=canonical_id)
        )
        if any(
            getattr(canonical, field) != getattr(row, field)
            for field in ("rsvp_id", "character_id", "kind", "status", "actors")
        ):
            raise ValueError("Calendar source alias does not match its canonical event")
        return canonical
    rsvp = row.rsvp
    if not row.event_key:
        row.origin = SYSTEM_ORIGINS.get(row.kind, "invitation")
        row.provenance_known = row.kind in SYSTEM_ORIGINS
        if (
            row.character_id == rsvp.character_id
            and row.status == rsvp.status
            and row.created_at >= rsvp.updated_at
        ):
            row.generation = rsvp.notice_generation
    if (
        row.provenance_known
        and row.origin == SYSTEM_ORIGINS.get(row.kind)
        and row.generation == rsvp.notice_generation
    ):
        compatible = (
            _system_transition_rows(
                rsvp,
                row.character_id,
                row.kind,
                row.status,
                row.actors,
                row.origin,
            )
            .select_related("rsvp__event", "character")
            .first()
        )
        if compatible is not None and compatible.pk != row.pk:
            canonical = _freeze(compatible)
            row.origin, row.provenance_known = canonical.origin, canonical.provenance_known
            row.generation, row.envelope = canonical.generation, canonical.envelope
            row.save(update_fields=["origin", "provenance_known", "generation", "envelope"])
            return canonical
    event = NoticeEvent(
        row.event_key or f"legacy-calendar-{row.pk}",
        row.created_at,
        subject=SubjectRef("rsvp", str(row.rsvp_id)),
        actors=tuple(ActorRef(**actor) for actor in row.actors),
        payload={
            "notice": row.pk,
            "event": rsvp.event_id,
            "generation": str(row.generation) if row.generation else "",
            "origin": row.origin,
            "status": row.status,
        },
        action_kind={"lottery": "lottery_selection", "waitlist_offer": "waitlist_offer"}.get(
            row.origin
        ),
    )
    row.envelope = asdict(event)
    row.envelope["occurred_at"] = event.occurred_at.isoformat()
    row.save(update_fields=["origin", "provenance_known", "generation", "envelope"])
    return row


def _record_disposition(row, state, *, acknowledged):
    """The canonical source claim/disposition also governs its frozen aliases."""
    now = timezone.now()
    values = {"route_state": state, "routed_at": now}
    if acknowledged:
        values["delivered_at"] = now
    for field, value in values.items():
        setattr(row, field, value)
    row.save(update_fields=list(values))
    type(row).objects.filter(
        rsvp_id=row.rsvp_id,
        character_id=row.character_id,
        envelope__payload__notice=row.pk,
    ).exclude(pk=row.pk).update(**values)


def _mirror_terminal(alias, canonical):
    """A historical source receipt wins even when its backend has been removed."""
    if canonical.delivered_at is not None or canonical.route_state in TERMINAL:
        alias.route_state = (
            canonical.route_state if canonical.route_state in TERMINAL else "fallback"
        )
        alias.delivered_at = canonical.delivered_at or canonical.routed_at
        alias.routed_at = canonical.routed_at or canonical.delivered_at
        alias.save(update_fields=["route_state", "delivered_at", "routed_at"])


def _standalone():
    """An omitted source is clean standalone composition; broken config is not."""
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if not isinstance(configured, dict):
        raise ValueError("Invalid notice source registry")
    # A broken explicit source must not leak raw fallback, even when disabled.
    if "calendar" in configured and "calendar" not in source_registry():
        raise ValueError("Calendar notice source unavailable")
    return (
        "calendar" not in configured
        or not apps.is_installed("evennia_notices")
        or not getattr(settings, "NOTICES_ENABLED", True)
    )


def _stored(row):
    from .integrations.notices import event_for

    return StoredEvent(
        **event_for(row).__dict__, recipient_kind="character", recipient_id=row.character_id
    )


def _finish_fallback(row_pk, character, message, sessions):
    """A committed source claim precedes socket I/O; uncertainty is never replayed."""
    from .integrations.notices import CalendarNoticeSource, currentness
    from .models import CalendarNotice

    row = CalendarNotice.objects.select_related("rsvp__event", "character").get(pk=row_pk)
    if currentness(row).status == "invalid":
        _record_disposition(row, "invalid", acknowledged=True)
        return
    if is_guest(row.character):
        _finish_guest_fallback(row, sessions)
        return
    source, event = CalendarNoticeSource(), _stored(row)
    eligible = []
    for session in sessions:
        context = NoticeContext(session.get_account(), character, session)
        if (
            authorize_context(context, character)
            and evaluate(source, [event], context)[event.event_id].status == "visible"
        ):
            eligible.append(session)
    if not eligible:
        _record_disposition(row, "uncertain", acknowledged=False)
        return
    try:
        character.msg(message, session=eligible)
    except Exception:
        _record_disposition(row, "uncertain", acknowledged=False)
        logger.warning("Calendar standalone delivery uncertain; preserving source receipt")
    else:
        _record_disposition(row, "fallback", acknowledged=True)


def _fallback(row):
    from evennia.accounts.models import AccountDB

    from .integrations.notices import CalendarNoticeSource

    if is_guest(row.character):
        return _guest_fallback(row)
    source, event = CalendarNoticeSource(), _stored(row)
    owners = list(AccountDB.objects.filter(pk__in=account_ids(row.character)))
    outcomes = [
        evaluate(source, [event], NoticeContext(owner, row.character))[event.event_id]
        for owner in owners
    ]
    if outcomes and all(o.status in {"hidden", "invalid"} for o in outcomes):
        return "suppressed"
    sessions = []
    for session in _connected_sessions(row.character):
        context = NoticeContext(session.get_account(), row.character, session)
        if (
            authorize_context(context, row.character)
            and evaluate(source, [event], context)[event.event_id].status == "visible"
        ):
            sessions.append(session)
    if not sessions:
        return "pending"
    # Existing source text is used only for a new structurally known producer.
    # Legacy text never supplies an author/permission decision.
    message = (
        row.message
        if row.event_key
        else normalize_rendered(
            source.render([event], NoticeContext(sessions[0].get_account(), row.character))
        ).text
    )
    row.route_state = "attempting"
    row.routed_at = timezone.now()
    row.save(update_fields=["route_state", "routed_at"])
    transaction.on_commit(lambda: _finish_fallback(row.pk, row.character, message, sessions))
    return "attempting"


def _route_locked(row, context=None, allow_fallback=True, new_event=False):
    from .integrations.notices import currentness, event_for

    canonical = _freeze(row)
    if canonical.pk != row.pk:
        consumed = canonical.delivered_at is not None or canonical.route_state in TERMINAL
        result = _route_locked(canonical, context=context, allow_fallback=allow_fallback)
        canonical.refresh_from_db()
        _mirror_terminal(row, canonical)
        return "duplicate" if consumed else result
    if row.delivered_at is not None or row.route_state in TERMINAL:
        return "duplicate"
    if row.route_state in {"attempting", "uncertain"}:
        return "held"
    outcome = currentness(row)
    if outcome.status == "invalid":
        result = "invalid"
    elif outcome.status == "defer":
        return "held"
    elif is_guest(row.character) or _standalone():
        result = _fallback(row) if allow_fallback else "pending"
    else:
        if new_event:
            routed = route_new_event(
                row.character, source="calendar", event=event_for(row), context=context
            )
        else:
            routed = transfer(
                row.character,
                source="calendar",
                event=event_for(row),
                transfer_id=f"calendar-source-{row.envelope['payload']['notice']}",
                context=context,
            )
        if routed.status in {"retained", "duplicate", "suppressed"}:
            result = "inbox" if routed.status != "suppressed" else "suppressed"
        else:
            return "retry"
    if result in TERMINAL:
        _record_disposition(row, result, acknowledged=True)
    return result


def route_notice(pk, context=None, allow_fallback=True):
    """Lock before reading mutable routing state and acknowledge only durable results."""
    from .models import RSVP, CalendarNotice

    rsvp_id = CalendarNotice.objects.values_list("rsvp_id", flat=True).get(pk=pk)
    with transaction.atomic():
        # Match notify/save order on row-locking backends as well as SQLite:
        # RSVP lifecycle, then source receipt, then the Inbox's account lock.
        RSVP.objects.filter(pk=rsvp_id).update(notice_generation=F("notice_generation"))
        CalendarNotice.objects.filter(pk=pk).update(route_state=F("route_state"))
        row = (
            CalendarNotice.objects.select_for_update()
            .select_related("rsvp__event", "character")
            .get(pk=pk)
        )
        if row.rsvp_id != rsvp_id:
            raise ValueError("Calendar notice subject changed during transfer")
        result = _route_locked(row, context=context, allow_fallback=allow_fallback)
    if result == "attempting":
        row.refresh_from_db()
        return "fallback" if row.route_state == "fallback" else "held"
    return result


def _guest_session_owned(session, character):
    """Authorize this connected puppet directly; guests have no web roster."""
    from evennia.accounts.models import AccountDB

    account = session.get_account()
    return (
        isinstance(account, AccountDB)
        and bool(account.pk)
        and bool(account.is_authenticated)
        and session.get_puppet() == character
        and (account.pk in account_ids(character) or character.account == account)
    )


def _guest_actor_policy(account, actors):
    """Resolve actual actors and apply the shared strict notice ignore policy."""
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from evennia_links.ignoring import notice_ignore_status

    for reference in actors:
        model = {"account": AccountDB, "character": ObjectDB}.get(reference.get("kind"))
        if model is None:
            return "defer"
        actor = model.objects.filter(pk=reference.get("id")).first()
        if actor is None:
            return "defer"
        outcome = notice_ignore_status(account, actor)
        if outcome != "allow":
            return outcome
    return "allow"


def _guest_fallback(row):
    """Claim only an existing guest history row; no new retained record is made."""
    owned = [
        s for s in _connected_sessions(row.character) if _guest_session_owned(s, row.character)
    ]
    if not owned:
        return "pending"
    policies = [_guest_actor_policy(s.get_account(), row.actors) for s in owned]
    if all(policy == "suppress" for policy in policies):
        return "suppressed"
    sessions = [
        session for session, policy in zip(owned, policies, strict=True) if policy == "allow"
    ]
    if not sessions:
        return "pending"
    row.route_state, row.routed_at = "attempting", timezone.now()
    row.save(update_fields=["route_state", "routed_at"])
    transaction.on_commit(lambda: _finish_fallback(row.pk, row.character, "", sessions))
    return "attempting"


def _finish_guest_fallback(row, sessions):
    """Recheck authoritative source state immediately before every guest socket."""
    from .integrations.notices import CalendarNoticeSource, currentness

    delivered = invalid = False
    for session in sessions:
        live = type(row).objects.select_related("rsvp__event", "character").get(pk=row.pk)
        outcome = currentness(live)
        if outcome.status == "invalid":
            invalid = True
            continue
        if (
            outcome.status != "visible"
            or not _guest_session_owned(session, live.character)
            or _guest_actor_policy(session.get_account(), live.actors) != "allow"
        ):
            continue
        text = normalize_rendered(
            CalendarNoticeSource().render(
                [_stored(live)], NoticeContext(session.get_account(), live.character)
            )
        ).text
        try:
            session.msg(text)
        except Exception:
            logger.warning("Calendar guest source delivery uncertain; preserving claim")
        else:
            delivered = True
    state = "fallback" if delivered else "invalid" if invalid else "uncertain"
    _record_disposition(row, state, acknowledged=delivered or invalid)


def _guest_notify(rsvp, kind, origin, actor):
    """Connected guest hints use fresh source truth and retain no new records."""
    from .models import RSVP

    expected = {
        "lottery": ("drawn", RSVP.Status.LOTTERY_SELECTED),
        "waitlist_offer": ("invited", RSVP.Status.INVITED),
        "invitation": ("invited", RSVP.Status.INVITED),
        "seated": ("seated", RSVP.Status.CONFIRMED),
        "reminder": ("reminder", RSVP.Status.CONFIRMED),
    }.get(origin)
    if expected is None or (origin in {"invitation", "waitlist_offer"} and actor is None):
        return False
    actors, shown = _actor_refs(actor), False
    for session in _connected_sessions(rsvp.character):
        live = RSVP.objects.select_related("event", "character").filter(pk=rsvp.pk).first()
        if (
            live is None
            or live.character_id is None
            or live.character_id != rsvp.character_id
            or live.event_id != rsvp.event_id
            or live.notice_generation != rsvp.notice_generation
            or expected != (kind, live.status)
            or live.event.is_cancelled
            or live.event.is_past
            or (kind in {"drawn", "invited"} and live.event.confirmation_deadline <= timezone.now())
            or not _guest_session_owned(session, live.character)
            or _guest_actor_policy(session.get_account(), actors) != "allow"
        ):
            continue
        marker = (
            f"{live.pk}-reminder"
            if kind == "reminder"
            else f"{live.pk}-{live.notice_generation}-{origin}"
        )
        seen = getattr(session, "_calendar_notice_hints", set())
        if marker in seen:
            continue
        session._calendar_notice_hints = seen | {marker}
        message = {
            "lottery": drawn_message,
            "waitlist_offer": offered_message,
            "invitation": invited_message,
            "seated": seated_message,
            "reminder": reminder_message,
        }[origin](live.event)
        try:
            session.msg(message)
        except Exception:
            logger.warning("Calendar guest hint uncertain; transient attempt retained")
        else:
            shown = True
    return shown


def notify(rsvp, kind, message, *, origin=None, actor=None):
    """Record a canonical transition and route it once; preserve the positional API.

    Human invitations require actor provenance. Existing custom callers without
    it retain a pending source record but never disclose guessed sender text.
    Returns True only when standalone delivery has completed now.
    """
    from .models import RSVP, CalendarNotice

    if rsvp.character_id is None:
        return False
    origin = origin or SYSTEM_ORIGINS.get(kind)
    if is_guest(rsvp.character):
        return _guest_notify(rsvp, kind, origin, actor)
    actors = _actor_refs(actor)
    with transaction.atomic():
        RSVP.objects.filter(pk=rsvp.pk).update(notice_generation=F("notice_generation"))
        live = RSVP.objects.select_for_update().select_related("event", "character").get(pk=rsvp.pk)
        if live.notice_generation != rsvp.notice_generation:
            return False
        key = (
            f"calendar-{live.pk}-reminder"
            if kind == "reminder"
            else f"calendar-{live.pk}-{live.notice_generation}-{origin or 'unknown'}"
        )
        existing_reminder = (
            CalendarNotice.objects.filter(rsvp=live, kind="reminder").first()
            if kind == "reminder"
            else None
        )
        existing_transition = (
            existing_reminder
            or _system_transition_rows(
                live,
                live.character_id,
                kind,
                live.status,
                actors,
                origin,
            )
            .select_related("rsvp__event", "character")
            .first()
        )
        row, created = (
            (existing_transition, False)
            if existing_transition is not None
            else CalendarNotice.objects.get_or_create(
                event_key=key,
                defaults=dict(
                    rsvp=live,
                    character=live.character,
                    kind=kind,
                    status=live.status,
                    message=message,
                    generation=live.notice_generation,
                    origin=origin or "invitation",
                    actors=actors,
                    provenance_known=bool(origin)
                    and (origin not in {"invitation", "waitlist_offer"} or bool(actors)),
                ),
            )
        )
        result = _route_locked(row, new_event=created)
    row.refresh_from_db()
    return result == "attempting" and row.route_state == "fallback"


def transfer_pending(
    character=None, *, batch_size=100, context=None, cursor=None, allow_fallback=False
):
    """Process one bounded pk page, persisting progress past held/retry rows."""
    from .models import CalendarNotice, CalendarNoticeCursor

    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if context is not None and (character is None or not authorize_context(context, character)):
        raise ValueError("Transfer context must own exactly the supplied character")
    scope = f"character-{character.pk}" if character is not None else "all"
    guest_scope = character is not None and is_guest(character)
    if guest_scope:
        progress = None
        previous = character.ndb.calendar_notice_cursor or 0
    else:
        progress, _ = CalendarNoticeCursor.objects.get_or_create(scope=scope)
        previous = progress.last_pk
    after = previous if cursor is None else int(cursor)
    query = CalendarNotice.objects.filter(delivered_at__isnull=True, pk__gt=after).order_by("pk")
    if character is not None:
        query = query.filter(character=character)
    ids = list(query.values_list("pk", flat=True)[: batch_size + 1])
    counts = dict(transferred=0, duplicate=0, suppressed=0, invalid=0, held=0, retry=0, delivered=0)
    for pk in ids[:batch_size]:
        try:
            result = route_notice(pk, context=context, allow_fallback=allow_fallback)
        except Exception:
            logger.warning("Calendar notice transfer deferred; source remains pending")
            result = "retry"
        name = {
            "inbox": "transferred",
            "fallback": "delivered",
            "attempting": "delivered",
            "pending": "held",
        }.get(result, result)
        counts[name] += 1
    complete = len(ids) <= batch_size
    next_cursor = 0 if complete else ids[batch_size - 1]
    if guest_scope:
        character.ndb.calendar_notice_cursor = next_cursor
    else:
        CalendarNoticeCursor.objects.filter(pk=progress.pk).update(last_pk=next_cursor)
    return {**counts, "next_cursor": next_cursor, "complete": complete}


def deliver_pending(character):
    """One source path at puppet; inbox transfers never also send raw text."""
    return transfer_pending(character, allow_fallback=True)["delivered"]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _when(event):
    return f"{event.scheduled_time.strftime(TIME_FORMAT)} UTC"


def _confirm_by(event):
    return (
        f"Confirm with |w+rsvp/confirm {event.pk}|n by "
        f"{event.confirmation_deadline.strftime(TIME_FORMAT)} UTC, "
        "or the place goes to someone else."
    )


def drawn_message(event):
    return f"|yYou were drawn for |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def invited_message(event, host=None):
    who = f"{host} has invited you" if host else "You've been invited"
    return f"|y{who} to |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def offered_message(event):
    return f"|yA place has opened for |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def seated_message(event):
    return (
        f"|yA place opened for |w'{event.title}'|n ({_when(event)}), "
        "and it's yours: you're confirmed.|n"
    )


def reminder_message(event):
    return f"|yReminder:|n |w'{event.title}'|n starts at {_when(event)}."


# ---------------------------------------------------------------------------
# Signal receivers
# ---------------------------------------------------------------------------


def _safely(what, rsvp, func):
    try:
        func()
    except Exception:
        logger.exception(
            "evennia_calendar.notices: %s notice failed for RSVP #%s",
            what,
            getattr(rsvp, "pk", "?"),
        )


def on_lottery_selected(sender, event=None, rsvp=None, **kwargs):
    """lottery_selected receiver: tell the player they were drawn."""
    _safely("drawn", rsvp, lambda: notify(rsvp, "drawn", drawn_message(event), origin="lottery"))


def on_cluster_seat_assigned(sender, rsvp=None, **kwargs):
    """cluster_seat_assigned receiver: a cluster draw seats like a lottery draw."""
    _safely(
        "drawn", rsvp, lambda: notify(rsvp, "drawn", drawn_message(rsvp.event), origin="lottery")
    )


def on_waitlist_promoted(sender, event=None, rsvp=None, **kwargs):
    """waitlist_promoted receiver: a place given outright, or offered to confirm."""
    from evennia_calendar.models import RSVP

    if rsvp.status == RSVP.Status.CONFIRMED:
        _safely(
            "seated", rsvp, lambda: notify(rsvp, "seated", seated_message(event), origin="seated")
        )
    elif rsvp.status == RSVP.Status.INVITED:
        _safely(
            "invited",
            rsvp,
            lambda: notify(
                rsvp,
                "invited",
                offered_message(event),
                origin="waitlist_offer",
                actor=kwargs.get("actor"),
            ),
        )


def on_event_starting_soon(sender, event=None, **kwargs):
    """event_starting_soon receiver: remind everyone confirmed, once each."""
    from evennia_calendar.models import RSVP

    if event is None or event.is_cancelled:
        return
    message = reminder_message(event)
    for rsvp in event.rsvps.filter(status=RSVP.Status.CONFIRMED).select_related("character"):
        _safely(
            "reminder", rsvp, lambda rsvp=rsvp: notify(rsvp, "reminder", message, origin="reminder")
        )


def on_post_puppet(sender, session=None, **kwargs):
    """SIGNAL_OBJECT_POST_PUPPET receiver: deliver waiting notices. Never raises."""
    try:
        deliver_pending(sender)
    except Exception:
        logger.exception(
            "evennia_calendar.notices: delivering notices failed for #%s",
            getattr(sender, "pk", "?"),
        )


def connect():
    """Connect the receivers. Called from ``CalendarConfig.ready()``; safe to repeat."""
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    from evennia_calendar import signals

    signals.lottery_selected.connect(
        on_lottery_selected, dispatch_uid="evennia_calendar.notice_drawn"
    )
    signals.cluster_seat_assigned.connect(
        on_cluster_seat_assigned, dispatch_uid="evennia_calendar.notice_cluster"
    )
    signals.waitlist_promoted.connect(
        on_waitlist_promoted, dispatch_uid="evennia_calendar.notice_waitlist"
    )
    signals.event_starting_soon.connect(
        on_event_starting_soon, dispatch_uid="evennia_calendar.notice_reminder"
    )
    SIGNAL_OBJECT_POST_PUPPET.connect(on_post_puppet, dispatch_uid="evennia_calendar.notices")
