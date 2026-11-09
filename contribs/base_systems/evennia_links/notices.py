# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional synchronous notice routing, independent of inbox models.

Sources own visibility, current action state and rendering. A clean unavailable
backend is the only condition allowing fallback; ambiguous failures are retryable.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from django.apps import apps
from django.conf import settings
from django.utils.module_loading import import_string
from django.utils.timezone import is_aware

logger = logging.getLogger("evennia")
SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ACTION_KINDS = {"lottery_selection", "waitlist_offer"}


@dataclass(frozen=True)
class SubjectRef:
    """Opaque source-owned subject reference."""

    kind: str
    key: str


@dataclass(frozen=True)
class ActorRef:
    """Identity reference; never an actor-supplied display name."""

    kind: str
    id: int


@dataclass(frozen=True)
class NoticeEvent:
    """Immutable transition identity and primitive source data."""

    event_id: str
    occurred_at: datetime
    subject: SubjectRef | None = None
    actors: tuple[ActorRef, ...] = ()
    payload: dict = field(default_factory=dict)
    replacement_key: str | None = None
    action_kind: str | None = None


@dataclass(frozen=True)
class NoticeContext:
    """Explicit account, selected playable character and delivery session."""

    account: object
    character: object = None
    session: object = None


@dataclass(frozen=True)
class Evaluation:
    """Current visibility and narrowly typed outstanding obligation."""

    status: str
    outstanding: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class NoticeAction:
    """Navigation or command instructions, never an executable callback."""

    label: str
    command: str | None = None
    route_name: str | None = None
    route_args: tuple = ()


@dataclass(frozen=True)
class RenderedNotice:
    """Plain text and safe route/command instructions."""

    text: str
    actions: tuple[NoticeAction, ...] = ()


@dataclass(frozen=True)
class RouteResult:
    """Durable routing outcome; unavailable is an internal backend sentinel."""

    status: str
    receipt: str | None = None


@dataclass(frozen=True)
class StoredEvent:
    """Source input with explicit recipient provenance."""

    event_id: str
    occurred_at: datetime
    subject: SubjectRef | None
    actors: tuple[ActorRef, ...]
    payload: dict
    replacement_key: str | None = None
    action_kind: str | None = None
    recipient_kind: str = ""
    recipient_id: int = 0


def validate_event(event):
    """Reject malformed programmer input before any backend can acknowledge it."""
    if not isinstance(event, NoticeEvent):
        raise ValueError("Expected NoticeEvent")
    if not isinstance(event.event_id, str) or not 1 <= len(event.event_id) <= 255:
        raise ValueError("Event identifier is required")
    for value in (event.replacement_key,):
        if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 255):
            raise ValueError("Event and replacement identifiers must be nonempty bounded strings")
    if not isinstance(event.occurred_at, datetime) or not is_aware(event.occurred_at):
        raise ValueError("Notice timestamp must be timezone aware")
    if event.action_kind is not None and event.action_kind not in ACTION_KINDS:
        raise ValueError("Unknown notice action kind")
    if event.subject is not None and (
        not isinstance(event.subject, SubjectRef)
        or not all(
            isinstance(v, str) and 0 < len(v) <= 255
            for v in (event.subject.kind, event.subject.key)
        )
    ):
        raise ValueError("Invalid notice subject")
    if not isinstance(event.actors, tuple) or any(
        not isinstance(a, ActorRef)
        or a.kind not in {"character", "account"}
        or type(a.id) is not int
        or a.id <= 0
        for a in event.actors
    ):
        raise ValueError("Invalid notice actors")
    if not isinstance(event.payload, dict):
        raise ValueError("Notice payload must be a JSON object")
    try:
        encoded = json.dumps(event.payload, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Notice payload must contain JSON primitives") from exc
    if len(encoded.encode()) > getattr(settings, "LINKS_NOTICE_MAX_PAYLOAD_BYTES", 16384):
        raise ValueError("Notice payload exceeds configured size")


def source_registry():
    """Resolve the current settings registry without leaking override-settings caches."""
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if not isinstance(configured, dict) or any(
        not isinstance(k, str) or not SLUG.fullmatch(k) or not isinstance(v, str)
        for k, v in configured.items()
    ):
        raise ValueError("LINKS_NOTICE_SOURCES must map lowercase slugs to dotted objects")
    return dict(_resolve_registry(tuple(sorted(configured.items()))))


@lru_cache(maxsize=32)
def _resolve_registry(configured):
    sources = []
    for slug, path in configured:
        try:
            source = import_string(path)
        except ImportError:
            logger.warning("Configured notice source unavailable")
            continue
        if isinstance(source, type):
            source = source()
        if not isinstance(getattr(source, "label", None), str) or not all(
            callable(getattr(source, method, None)) for method in ("evaluate", "render")
        ):
            raise ValueError("Notice source must supply label, evaluate and render")
        sources.append((slug, source))
    return tuple(sources)


def recipient_identity(recipient):
    """Return canonical ownership, rejecting arbitrary objects and non-playables."""
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from .characters import playable_accounts

    if isinstance(recipient, AccountDB) and recipient.pk:
        return "account", recipient.pk
    if (
        isinstance(recipient, ObjectDB)
        and recipient.pk
        and any(recipient.pk in {c.pk for c in chars} for _, chars in playable_accounts())
    ):
        return "character", recipient.pk
    raise ValueError("Notice recipient must be an account or playable character")


def authorize_context(context, recipient=None):
    """Validate explicit scope without guessing an account's other puppets."""
    from evennia.accounts.models import AccountDB

    from .characters import web_roster

    if (
        not isinstance(context, NoticeContext)
        or not isinstance(context.account, AccountDB)
        or not context.account.pk
    ):
        return False
    if context.character is not None and context.character.pk not in {
        c.pk for c in web_roster(context.account)
    }:
        return False
    if context.session is not None and (
        context.session.get_account() != context.account
        or (context.character is not None and context.session.get_puppet() != context.character)
    ):
        return False
    if recipient is None:
        return True
    kind, pk = recipient_identity(recipient)
    return pk == (
        context.account.pk if kind == "account" else getattr(context.character, "pk", None)
    )


def evaluate(source, events, context, policy_cache=None):
    """Evaluate one source/owner batch and strict optional ignore policy."""
    from .ignoring import notice_ignore_status

    try:
        outcomes = source.evaluate(events, context)
        if set(outcomes) != {e.event_id for e in events}:
            raise ValueError("Source omitted or added event evaluations")
        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        actors = {"account": {}, "character": {}}
        for kind, model in (("account", AccountDB), ("character", ObjectDB)):
            ids = {a.id for e in events for a in e.actors if a.kind == kind}
            if ids:
                actors[kind] = model.objects.in_bulk(ids)
        policy_cache = {} if policy_cache is None else policy_cache
        result = {}
        for event in events:
            outcome = outcomes[event.event_id]
            if not isinstance(outcome, Evaluation) or outcome.status not in {
                "visible",
                "hidden",
                "invalid",
                "defer",
            }:
                raise ValueError("Invalid source evaluation")
            if outcome.outstanding and event.action_kind not in ACTION_KINDS:
                raise ValueError("Untyped outstanding action")
            if outcome.status == "visible" or (
                outcome.status == "defer" and outcome.reason == "context"
            ):
                for actor in event.actors:
                    sender = actors[actor.kind].get(actor.id)
                    if sender is None:
                        raise ValueError("Notice actor no longer available")
                    key = (actor.kind, actor.id)
                    if key not in policy_cache:
                        policy_cache[key] = notice_ignore_status(
                            context.account, sender, policy_cache=policy_cache
                        )
                    mode = policy_cache[key]
                    if mode == "defer":
                        raise ValueError("Notice ignore policy unavailable")
                    if mode == "suppress":
                        outcome = Evaluation("hidden")
            result[event.event_id] = outcome
        return result
    except Exception:
        logger.warning("Notice evaluation unavailable; deferring source batch")
        return {e.event_id: Evaluation("defer", reason="temporary") for e in events}


def session_context(session):
    """Use an owned playable puppet, or safe account-only scope for this connection."""
    from .characters import web_roster

    account = session.get_account()
    puppet = session.get_puppet()
    character = next((candidate for candidate in web_roster(account) if candidate == puppet), None)
    return NoticeContext(account, character, session)


def connected_contexts(recipient):
    """Yield only sessions eligible for the addressed ownership."""
    from evennia.accounts.models import AccountDB
    from evennia.server.sessionhandler import SESSIONS

    for session in SESSIONS.get_sessions():
        account = session.get_account()
        character = session.get_puppet()
        if (isinstance(recipient, AccountDB) and account == recipient) or character == recipient:
            context = session_context(session)
            if authorize_context(context, recipient):
                yield context


def normalize_rendered(value):
    """Validate source output and remove terminal/control sequences consistently."""
    from evennia.utils.ansi import strip_ansi

    def clean(text):
        if not isinstance(text, str):
            raise ValueError("Notice presentation must be text")
        text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        text = strip_ansi(text)
        return "".join(
            c for c in text if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf"}
        )

    if not isinstance(value, RenderedNotice) or not isinstance(value.actions, tuple):
        raise ValueError("Source must return RenderedNotice")
    actions = []
    for action in value.actions:
        if not isinstance(action, NoticeAction) or not isinstance(action.route_args, tuple):
            raise ValueError("Invalid notice action")
        if action.route_name is not None and (
            not isinstance(action.route_name, str)
            or not re.fullmatch(r"[A-Za-z0-9_:.-]+", action.route_name)
        ):
            raise ValueError("Notice action must use a local named route")
        if any(type(arg) not in (str, int) for arg in action.route_args):
            raise ValueError("Invalid notice route argument")
        actions.append(
            NoticeAction(
                clean(action.label),
                clean(action.command) if action.command is not None else None,
                action.route_name,
                action.route_args,
            )
        )
    return RenderedNotice(clean(value.text), tuple(actions))


def default_fallback(recipient, event, context, source):
    """Render to every eligible connected session; offline work stays pending."""
    delivered = saw_session = False
    all_denied = True
    contexts = [context] if context and context.session else connected_contexts(recipient)
    for current in contexts:
        if not authorize_context(current, recipient):
            continue
        saw_session = True
        kind, pk = recipient_identity(recipient)
        stored = StoredEvent(**event.__dict__, recipient_kind=kind, recipient_id=pk)
        outcome = evaluate(source, [stored], current)[event.event_id]
        if outcome.status in {"hidden", "invalid"}:
            continue
        all_denied = False
        if outcome.status != "visible":
            continue
        try:
            rendered = normalize_rendered(source.render([stored], current))
            current.session.msg(rendered.text)
            delivered = True
        except Exception:
            logger.warning("Notice fallback delivery failed; source work remains pending")
    return RouteResult(
        "delivered"
        if delivered
        else "suppressed"
        if saw_session and all_denied
        else "fallback_pending"
    )


def notify(recipient, *, source, event, fallback=None, context=None, transfer_id=None):
    """Choose exactly one durable backend or a clean unavailable fallback path."""
    from .guests import is_guest

    validate_event(event)
    recipient_identity(recipient)
    if not isinstance(source, str) or not SLUG.fullmatch(source):
        raise ValueError("Invalid notice source slug")
    if context is not None and not authorize_context(context, recipient):
        raise ValueError("Unauthorized notice context")
    if apps.is_installed("evennia_notices") and not is_guest(recipient):
        try:
            from evennia_notices.services import route

            result = route(
                recipient, source=source, event=event, context=context, transfer_id=transfer_id
            )
        except Exception:
            logger.warning("Notice backend failed; retry without fallback")
            return RouteResult("retry")
        if result.status != "unavailable":
            return result
    try:
        adapter = source_registry()[source]
    except KeyError as exc:
        raise ValueError("Unregistered notice source") from exc
    if fallback is not None:
        return fallback(recipient, event, context)
    return default_fallback(recipient, event, context, adapter)


def transfer(recipient, *, source, event, transfer_id, context=None, fallback=None):
    """Route a stable source-owned legacy receipt through the same identity path."""
    if not isinstance(transfer_id, str) or not 0 < len(transfer_id) <= 255:
        raise ValueError("Invalid transfer identifier")
    return notify(
        recipient,
        source=source,
        event=event,
        context=context,
        fallback=fallback,
        transfer_id=transfer_id,
    )
