# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Discovery and transport for account-owned subscribed Boards activity."""

import logging

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_boards.integrations.notices import POST_FIELDS, SOURCE, event_for
from evennia_boards.models import Post, StandaloneNoticeClaim, Subscription
from evennia_links.guests import is_guest
from evennia_links.ignoring import notice_ignore_status
from evennia_links.notices import NoticeContext, RouteResult, notify, source_registry, transfer

logger = logging.getLogger("evennia")
BATCH = 100
_INITIAL = object()
Status = StandaloneNoticeClaim.Status


class RetryDiscovery(Exception):
    """Leave the entire source scope eligible for a later attempt."""


def _inbox_enabled():
    if not apps.is_installed("evennia_notices") or not getattr(settings, "NOTICES_ENABLED", True):
        return False
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if isinstance(configured, dict) and SOURCE not in configured:
        return False
    if SOURCE not in source_registry():
        raise RetryDiscovery("Configured Boards notice source is unavailable")
    return True


def _account_lock(account_id):
    AccountDB.objects.filter(pk=account_id).update(last_login=F("last_login"))
    account = AccountDB.objects.select_for_update().get(pk=account_id)
    account.attributes.reset_cache()
    return account


def _subscriptions(account_id):
    return Subscription.objects.filter(account_id=account_id).order_by(
        "board__order", "board__name", "pk"
    )


def _scope(subscription, *, position=_INITIAL, ceiling=None, inbox=False):
    upper = Post.all_objects.filter(board_id=subscription.board_id).aggregate(last=Max("pk"))[
        "last"
    ]
    if ceiling is not None:
        upper = min(upper or 0, ceiling)
    position = subscription.discovery_post_id if position is _INITIAL else position
    legacy = position is None and (not inbox or subscription.inbox_start_post_id is None)
    cutoff = subscription.last_notified_at if legacy else None
    return [position or 0, max(upper or 0, position or 0), cutoff.isoformat() if cutoff else None]


def _scope_filter(scope, *, floor=0):
    lower, upper, cutoff = scope
    condition = Q(pk__gt=max(lower, floor), pk__lte=upper)
    if cutoff is not None:
        condition &= Q(created_at__gt=parse_datetime(cutoff))
    return condition


def _checkpoint(subscription, upper, *, acknowledged):
    fields = {"discovery_post_id": upper}
    if acknowledged:
        fields["last_notified_at"] = timezone.now()
    Subscription.objects.filter(pk=subscription.pk).update(**fields)


class _StrictPolicy:
    def __init__(self, account):
        self.account = account
        self.cache = {}
        self.statuses = {}

    def load(self, rows):
        ids = {row[2] for row in rows if row[2] is not None and row[2] not in self.statuses}
        for author_id, actor in ObjectDB.objects.in_bulk(ids).items():
            self.statuses[author_id] = notice_ignore_status(
                self.account, actor, policy_cache=self.cache
            )
        for author_id in ids - self.statuses.keys():
            self.statuses[author_id] = "suppress"

    def status(self, row):
        return "allow" if row[2] is None else self.statuses[row[2]]


def _pages(posts):
    query = posts.order_by("-pk").values_list(*POST_FIELDS)
    while rows := list(query[:BATCH]):
        yield rows
        query = query.filter(pk__lt=rows[-1][0])


def _fallback(*args):
    return RouteResult("retry")


def _disposition(result, account):
    if result.status == "duplicate":
        from evennia_notices.models import DeliveryReceipt

        return DeliveryReceipt.objects.get(
            pk=result.receipt, recipient__account=account, source=SOURCE
        ).disposition
    return result.status


def _eligible_posts(account, subscription, scope, *, floor):
    return Post.objects.filter(
        _scope_filter(scope, floor=floor), board_id=subscription.board_id
    ).exclude(read_suppressions__account_id=account.pk)


def _witnesses(subscription, posts, *, policy=None):
    for rows in _pages(posts):
        if policy is not None:
            policy.load(rows)
        for row in rows:
            event = event_for(subscription, row)
            if event is None:
                continue
            if policy is not None:
                status = policy.status(row)
                if status == "defer":
                    raise RetryDiscovery("Boards ignore policy is unavailable")
                if status != "allow":
                    continue
            yield row, event


def _route_witness(account, subscription, scopes, *, policy, off, fresh_post):
    floor = max(subscription.inbox_start_post_id or 0, subscription.inbox_witness_post_id or 0)
    for scope in sorted(scopes, key=lambda scope: scope[1], reverse=True):
        posts = _eligible_posts(account, subscription, scope, floor=floor)
        for row, event in _witnesses(subscription, posts, policy=None if off else policy):
            witness = (
                posts.select_for_update()
                .filter(pk=row[0])
                .order_by()
                .values_list(*POST_FIELDS)
                .first()
            )
            if witness != row:
                continue
            args = {"source": SOURCE, "event": event, "fallback": _fallback}
            result = (
                notify(account, **args)
                if fresh_post == row[0]
                else transfer(account, transfer_id=f"transfer-{event.event_id}", **args)
            )
            status = _disposition(result, account)
            if status == "retained":
                return row[0]
            if status != "suppressed":
                raise RetryDiscovery("Boards notice was not acknowledged")
            if off:
                return None
    return None


def _prepare_locked(account, *, board_id=None, fresh_post=None):
    from evennia_notices.services import effective_mode

    off = effective_mode(account, SOURCE) == "off"
    policy = _StrictPolicy(account)
    pending = list(StandaloneNoticeClaim.objects.filter(account=account, status=Status.PENDING))
    subscriptions = _subscriptions(account.pk)
    if board_id is not None:
        subscriptions = subscriptions.filter(board_id=board_id)
    handled = set()
    for subscription in subscriptions.iterator(chunk_size=BATCH):
        current = _scope(subscription, ceiling=fresh_post, inbox=True)
        key = str(subscription.pk)
        older = [claim.ranges[key] for claim in pending if key in claim.ranges]
        witness = _route_witness(
            account, subscription, [current, *older], policy=policy, off=off, fresh_post=fresh_post
        )
        if witness is not None:
            Subscription.objects.filter(pk=subscription.pk).update(inbox_witness_post_id=witness)
        if older or current[1] != subscription.discovery_post_id:
            _checkpoint(subscription, current[1], acknowledged=True)
        handled.add(key)

    # A live post can cover its own board's pending scopes. A full preparation
    # also seals scopes whose subscription generation has since disappeared.
    for claim in pending:
        remaining = {key: scope for key, scope in claim.ranges.items() if key not in handled}
        if not remaining or board_id is None:
            _set_status(claim, Status.TRANSFERRED)
        elif len(remaining) != len(claim.ranges):
            # Keep the immutable original claim intact and stage only its
            # unhandled boards for fallback or a later preparation.
            StandaloneNoticeClaim.objects.create(account=account, ranges=remaining)
            _set_status(claim, Status.TRANSFERRED)


def prepare_account(account_id, *, board_id=None, fresh_post=None):
    """Account-first quiet discovery, with an exact fresh commit witness when supplied."""
    try:
        if not _inbox_enabled():
            return
        account = AccountDB.objects.get(pk=account_id)
        if is_guest(account):
            if fresh_post is not None:
                _guest_login(account, _sessions(None), True, board_id=board_id)
            return
        with transaction.atomic():
            account = _account_lock(account_id)
            if not is_guest(account):
                _prepare_locked(account, board_id=board_id, fresh_post=fresh_post)
    except AccountDB.DoesNotExist:
        pass
    except Exception:
        logger.warning("Boards notice discovery deferred", exc_info=True)


def post_committed(board_id, post_id):
    """Discover committed activity one subscriber at a time."""
    try:
        if not _inbox_enabled():
            return
        subscribers = (
            Subscription.objects.filter(board_id=board_id)
            .order_by("account_id")
            .values_list("account_id", flat=True)
        )
        for account_id in subscribers.iterator(chunk_size=BATCH):
            prepare_account(account_id, board_id=board_id, fresh_post=post_id)
    except Exception:
        logger.warning("Boards post subscriber discovery deferred", exc_info=True)


def _set_status(claim, status):
    claim.status = status
    claim.save(update_fields=["status", "updated_at"])


def _legacy_count(account, subscription, scope, policy, *, persist_hidden):
    from evennia_boards.presentation import unread_post_count

    posts = (
        Post.objects.filter(_scope_filter(scope), board_id=subscription.board_id)
        .select_related("author", "board", "parent_post", "parent_post__author")
        .order_by("pk")
    )
    return unread_post_count(
        account, posts, context=policy, persist_hidden=persist_hidden, account_locked=persist_hidden
    )


def _sessions(session):
    if session is not None:
        return (session,)
    from evennia.server.sessionhandler import SESSIONS

    return tuple(SESSIONS.get_sessions())


def _live_session(session, account):
    from evennia.server.sessionhandler import SESSIONS

    return (
        any(current is session for current in SESSIONS.get_sessions())
        and session.get_account() == account
        and AccountDB.objects.filter(pk=account.pk).exists()
    )


def _any_session(sessions, account):
    for session in sessions:
        try:
            if _live_session(session, account):
                return True
        except Exception:
            logger.warning("Boards session eligibility unavailable", exc_info=True)
    return False


def _legacy_activity(account, ranges):
    from evennia_boards.presentation import PolicyContext

    policy = PolicyContext(account)
    subscriptions = _subscriptions(account.pk).filter(pk__in=ranges).select_related("board")
    activity = []
    for subscription in subscriptions:
        count = _legacy_count(
            account, subscription, ranges[str(subscription.pk)], policy, persist_hidden=True
        )
        if count:
            activity.append((subscription.board, count))
    return activity


def _legacy_text(activity):
    lines = ["|wNew board posts:|n"]
    for board, count in activity:
        lines.append(f"  |w{board.name}|n: {count} new post{'s' if count != 1 else ''}")
    lines.append("Use |w+bb <board>|n to read.")
    return "\n".join(lines)


def _legacy_signal(account, activity):
    from evennia_boards.signals import board_unread_notified

    for board, count in activity:
        board_unread_notified.send_robust(
            sender=Subscription, account=account, board=board, unread_count=count
        )


def _stage_standalone(account):
    from evennia_boards.presentation import PolicyContext

    reservations = set()
    claims = StandaloneNoticeClaim.objects.filter(
        account=account, status__in=(Status.PENDING, Status.ATTEMPTING)
    ).order_by("pk")
    for claim in claims.iterator(chunk_size=BATCH):
        if claim.status == Status.PENDING and _legacy_activity(account, claim.ranges):
            return claim
        reservations.update(claim.ranges)
    policy = PolicyContext(account)
    ranges = {}
    for subscription in _subscriptions(account.pk).iterator(chunk_size=BATCH):
        scope = _scope(subscription)
        key = str(subscription.pk)
        count = _legacy_count(account, subscription, scope, policy, persist_hidden=True)
        if count:
            ranges[key] = scope
        _checkpoint(subscription, scope[1], acknowledged=not count and key not in reservations)
    return StandaloneNoticeClaim.objects.create(account=account, ranges=ranges) if ranges else None


def _attempt_standalone(claim_id, account_id, sessions):
    attempted = delivered = False
    for session in sessions:
        reserved = False
        try:
            with transaction.atomic():
                account = _account_lock(account_id)
                if _inbox_enabled() or is_guest(account) or not _live_session(session, account):
                    continue
                claim = StandaloneNoticeClaim.objects.get(pk=claim_id, account=account)
                expected = Status.ATTEMPTING if attempted else Status.PENDING
                if claim.status != expected:
                    return
                activity = _legacy_activity(account, claim.ranges)
                if not activity:
                    continue
                message = _legacy_text(activity)
                send = session.msg
                if not callable(send) or not _live_session(session, account):
                    continue
                if not attempted:
                    _set_status(claim, Status.ATTEMPTING)
            reserved = not attempted
            # Stay outside the transaction for socket I/O. The committed claim
            # fences other logins and transfers while assessing write outcomes.
            if not _live_session(session, account):
                continue
            first = not attempted
            attempted = True
            try:
                send(message)
                delivered = True
            finally:
                if first:
                    _legacy_signal(account, activity)
        except Exception:
            logger.warning("Boards standalone delivery interrupted", exc_info=True)
        finally:
            if reserved and not attempted:
                _finish_standalone(claim_id, account_id, Status.PENDING)
    if attempted:
        _finish_standalone(
            claim_id, account_id, Status.DELIVERED if delivered else Status.UNCERTAIN
        )


def _finish_standalone(claim_id, account_id, state):
    with transaction.atomic():
        account = _account_lock(account_id)
        claim = StandaloneNoticeClaim.objects.get(pk=claim_id, account=account)
        if claim.status != Status.ATTEMPTING:
            return
        _set_status(claim, state)
        if state != Status.PENDING:
            _subscriptions(account_id).filter(pk__in=claim.ranges).update(
                last_notified_at=timezone.now()
            )


def _guest_counts(account, scopes):
    from evennia_boards.presentation import PolicyContext

    policy = PolicyContext(account)
    return [
        (subscription.board, count)
        for subscription, scope in scopes
        if (count := _legacy_count(account, subscription, scope, policy, persist_hidden=False))
    ]


def _guest_inbox_message(account, scopes):
    from evennia_boards.integrations.notices import BoardNoticeSource
    from evennia_links.notices import normalize_rendered

    policy = _StrictPolicy(account)
    events = []
    for subscription, scope in scopes:
        posts = _eligible_posts(
            account, subscription, scope, floor=subscription.inbox_start_post_id or 0
        )
        witness = next(_witnesses(subscription, posts, policy=policy), None)
        if witness is not None:
            events.append(witness[1])
    if not events:
        return None
    from evennia_links.notices import StoredEvent

    stored = [
        StoredEvent(**event.__dict__, recipient_kind="account", recipient_id=account.pk)
        for event in events
    ]
    return normalize_rendered(BoardNoticeSource().render(stored, NoticeContext(account))).text


def _guest_login(account, sessions, inbox_enabled, *, board_id=None):
    for session in sessions:
        try:
            if not _live_session(session, account):
                continue
            owner, positions = getattr(session, "_boards_notice_positions", (None, {}))
            positions = positions if owner == account.pk else {}
            subscriptions = _subscriptions(account.pk).select_related("board")
            if board_id is not None:
                subscriptions = subscriptions.filter(board_id=board_id)
            scopes = [
                (sub, _scope(sub, position=positions.get(sub.pk), inbox=inbox_enabled))
                for sub in subscriptions
            ]
            activity = [] if inbox_enabled else _guest_counts(account, scopes)
            message = (
                _guest_inbox_message(account, scopes)
                if inbox_enabled
                else _legacy_text(activity)
                if activity
                else None
            )
            send = session.msg if message else None
            if message and not callable(send):
                continue
            if not _live_session(session, account):
                continue
            session._boards_notice_positions = (
                account.pk,
                positions | {sub.pk: scope[1] for sub, scope in scopes},
            )
            if send is not None:
                try:
                    send(message)
                finally:
                    _legacy_signal(account, activity)
        except Exception:
            logger.warning("Boards guest delivery interrupted", exc_info=True)


def notify_login(account, session=None):
    """Run the one legacy login sweep, or transient delivery for a live guest."""
    try:
        inbox_enabled = _inbox_enabled()
        if is_guest(account):
            _guest_login(account, _sessions(session), inbox_enabled)
            return
        if inbox_enabled:
            return
        sessions = _sessions(session)
        if not _any_session(sessions, account):
            return
        with transaction.atomic():
            locked = _account_lock(account.pk)
            if _inbox_enabled() or not _any_session(sessions, locked):
                return
            claim = _stage_standalone(locked)
            if claim is not None:
                transaction.on_commit(
                    lambda: _safe_standalone(claim.pk, locked.pk, sessions),
                    robust=True,
                )
    except Exception:
        logger.warning("Boards login sweep deferred", exc_info=True)


def _safe_standalone(claim_id, account_id, sessions):
    try:
        _attempt_standalone(claim_id, account_id, sessions)
    except Exception:
        logger.warning("Boards standalone claim could not be finalized", exc_info=True)
