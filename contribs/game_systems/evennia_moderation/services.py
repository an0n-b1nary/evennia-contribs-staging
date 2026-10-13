# SPDX-License-Identifier: BSD-3-Clause
"""Staff-only action services and automatic retention maintenance."""

import ipaddress
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from evennia_moderation.admissions import expire_applications
from evennia_moderation.config import value
from evennia_moderation.models import (
    Application,
    ApplicationThrottle,
    ModerationAction,
    ReferralCode,
    StaffNote,
)
from evennia_moderation.policy import require_staff


def _disconnect(action):
    from evennia import SESSION_HANDLER

    from evennia_moderation.policy import address_matches

    for session in SESSION_HANDLER.get_sessions():
        account = session.get_account()
        address = (
            session.address[0] if isinstance(session.address, (tuple, list)) else session.address
        )
        if (account and account.pk == action.account_id) or address_matches(action, address):
            SESSION_HANDLER.disconnect(session, reason="A moderation ban has been applied.")
    if action.account_id:
        from django.contrib.sessions.models import Session

        for session in Session.objects.filter(expire_date__gt=timezone.now()):
            if session.get_decoded().get("_auth_user_id") == str(action.account_id):
                session.delete()


@transaction.atomic
def restrict(actor, *, kind, account=None, address="", reason, hours=None):
    staff = require_staff(actor)
    if kind not in {"softban", "mute"}:
        raise ValidationError("Choose softban or mute.")
    if (not account and not address) or (kind == "mute" and not account):
        raise ValidationError(
            "A target account is required for a mute; a ban needs an account or address."
        )
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 10000:
        raise ValidationError("Give a reason of 1 to 10,000 characters.")
    if address:
        try:
            address = str(ipaddress.ip_network(address, strict=False))
        except ValueError as exc:
            raise ValidationError("Use an IP address or CIDR network.") from exc
    if hours is None and kind == "softban":
        hours = value("SOFTBAN_HOURS")
    if hours is not None and (type(hours) is not int or not 0 < hours <= 876000):
        raise ValidationError(
            "Duration must be a positive whole number of hours, at most 100 years."
        )
    action = ModerationAction.objects.create(
        kind=kind,
        account=account,
        account_name=account.key if account else "",
        address=address,
        actor=staff,
        actor_name=staff.key,
        reason=reason.strip(),
        ends_at=timezone.now() + timedelta(hours=hours) if hours else None,
    )
    if kind == "softban":
        transaction.on_commit(lambda: _disconnect(action))
    return action


@transaction.atomic
def lift(actor, action, *, reason="Lifted by staff"):
    staff = require_staff(actor)
    action = ModerationAction.objects.select_for_update().get(pk=action.pk)
    if action.kind in {"lift", "ban"}:
        raise ValidationError("This record is not a restriction.")
    if action.lifted_at:
        return action
    action.lifted_at = timezone.now()
    action.save(update_fields=["lifted_at"])
    ModerationAction.objects.create(
        kind="lift",
        account=action.account,
        account_name=action.account_name,
        actor=staff,
        actor_name=staff.key,
        reason=reason,
        lifts=action,
    )
    return action


def add_note(actor, account, text):
    staff = require_staff(actor)
    if not text.strip() or len(text) > 10000:
        raise ValidationError("Give a note of 1 to 10,000 characters.")
    return StaffNote.objects.create(
        account=account,
        account_name=account.key,
        actor=staff,
        actor_name=staff.key,
        text=text.strip(),
    )


def purge():
    """Daily task; expiry checks themselves never depend on sweep timing."""
    expire_applications()
    now = timezone.now()
    cutoff = now - timedelta(days=90)
    Application.objects.exclude(status="pending").filter(decided_at__lte=cutoff).update(
        address=None
    )
    ModerationAction.objects.filter(Q(lifted_at__lte=cutoff) | Q(ends_at__lte=cutoff)).update(
        address=""
    )
    ApplicationThrottle.objects.filter(expires_at__lte=now).delete()
    ReferralCode.objects.filter(used_at__isnull=True, expires_at__lte=now).update(code="")


@transaction.atomic
def record_stock_changes(actor, before, after):
    """Capture only actual changes made by the stock commands we wrap."""
    import hashlib
    from collections import Counter

    from evennia.accounts.models import AccountDB

    from evennia_moderation.policy import acting_account

    staff = acting_account(actor)

    def key(entry):
        return hashlib.sha256(repr((entry[0], entry[1], entry[3], entry[4])).encode()).hexdigest()

    old = Counter(key(entry) for entry in before)
    new = Counter(key(entry) for entry in after)
    entries = {key(entry): entry for entry in after}
    for digest in (new - old).elements():
        entry = entries[digest]
        account = AccountDB.objects.filter(username__iexact=entry[0]).first() if entry[0] else None
        action = ModerationAction.objects.create(
            kind="ban",
            account=account,
            account_name=entry[0],
            address=entry[2].pattern if entry[2] else "",
            address_is_pattern=bool(entry[2]),
            actor=staff,
            actor_name=staff.key,
            reason=entry[4] or "No reason supplied",
            stock_key=digest,
        )
        transaction.on_commit(lambda action=action: _disconnect(action))
    for digest, count in (old - new).items():
        actions = ModerationAction.objects.filter(
            stock_key=digest, lifted_at__isnull=True
        ).order_by("pk")[:count]
        for action in actions:
            action.lifted_at = timezone.now()
            action.save(update_fields=["lifted_at"])
            ModerationAction.objects.create(
                kind="lift",
                account=action.account,
                account_name=action.account_name,
                actor=staff,
                actor_name=staff.key,
                reason="Stock ban lifted",
                lifts=action,
            )
