# SPDX-License-Identifier: BSD-3-Clause
"""Account-wide restrictions, including offline alts and shared rosters."""

import ipaddress
import re

from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.utils import timezone
from evennia.accounts.models import AccountDB

from evennia_links.characters import account_ids
from evennia_moderation.config import value
from evennia_moderation.models import ModerationAction


def accounts_for(actor):
    if isinstance(actor, AccountDB):
        return [actor]
    ids = set(account_ids(actor))
    account = getattr(actor, "account", None)
    if account:
        ids.add(account.pk)
    return list(AccountDB.objects.filter(pk__in=ids))


def acting_account(actor):
    if isinstance(actor, AccountDB):
        return actor
    live = getattr(actor, "account", None)
    if live:
        return live
    accounts = accounts_for(actor)
    if len(accounts) == 1:
        return accounts[0]
    raise PermissionDenied("An unambiguous account is required.")


def _staff_permission():
    from django.conf import settings

    return getattr(settings, "MODERATION_STAFF_PERMISSION", "Builder")


def staff_account(account):
    """Current account status; never the puppet's permissions or quelled lock."""
    return bool(
        account and (account.is_superuser or account.permissions.check(_staff_permission()))
    )


def staff_accounts():
    """Queryset form of staff_account() that never loads every account.

    An account passes Evennia's perm() check when one of its permission keys
    passes on its own, so each distinct key in use is tested with perm()
    itself. That keeps hierarchy and plural handling identical to Evennia's.
    """
    from types import SimpleNamespace

    from evennia.locks.lockfuncs import perm

    permission = _staff_permission()
    held = (
        AccountDB.objects.filter(db_tags__db_tagtype="permission")
        .order_by()
        .values_list("db_tags__db_key", flat=True)
        .distinct()
    )
    keys = [
        key
        for key in held
        if perm(
            SimpleNamespace(permissions=SimpleNamespace(all=lambda key=key: [key])),
            None,
            permission,
        )
    ]
    return AccountDB.objects.filter(
        Q(is_superuser=True) | Q(db_tags__db_tagtype="permission", db_tags__db_key__in=keys)
    )


def require_staff(actor):
    lock = value("STAFF_LOCK").removeprefix("cmd:")
    try:
        allowed = actor.locks.check_lockstring(actor, lock)
    except Exception:
        allowed = False
    if not allowed:
        raise PermissionDenied("Only moderation staff may do that.")
    return acting_account(actor)


def active_actions(kind=None):
    qs = (
        ModerationAction.objects.filter(lifted_at__isnull=True)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=timezone.now()))
        .exclude(kind=ModerationAction.Kind.LIFT)
    )
    return qs.filter(kind=kind) if kind else qs


def address_matches(action, address):
    if not action.address or not address:
        return False
    try:
        if action.address_is_pattern:
            return bool(re.match(action.address, address))
        return ipaddress.ip_address(address) in ipaddress.ip_network(action.address, strict=False)
    except (ValueError, re.error):
        return False


def connection_restriction(account=None, username="", address=""):
    matching = []
    for action in active_actions().filter(kind__in=["ban", "softban"]):
        if (
            (account is not None and action.account_id == account.pk)
            or (username and action.account_name.casefold() == username.casefold())
            or address_matches(action, address)
        ):
            matching.append(action)
    if matching:
        action = max(
            matching, key=lambda item: (item.ends_at is None, item.ends_at or timezone.now())
        )
        until = action.ends_at.isoformat() if action.ends_at else "lifted by staff"
        return f"This account or address is banned until {until}."
    return None


def stock_bans():
    """Bypass Evennia's process-local ServerConfig identity cache."""
    from evennia.server.models import ServerConfig
    from evennia.utils.dbserialize import from_pickle

    raw = (
        ServerConfig.objects.filter(db_key="server_bans").values_list("db_value", flat=True).first()
    )
    return (from_pickle(raw) or []) if raw is not None else []


def stock_banned(username="", address=""):
    return any(
        (username and entry[0].strip().casefold() == username.strip().casefold())
        or (address and entry[2] and entry[2].match(address))
        for entry in stock_bans()
    )


def communication_policy(sender, *, actor, kind, target=None, **kwargs):
    accounts = accounts_for(actor)
    mute = (
        active_actions("mute")
        .filter(account_id__in=[a.pk for a in accounts])
        .order_by(F("ends_at").desc(nulls_first=True))
        .first()
    )
    if not mute:
        return None
    if (
        kind == "page"
        and target is not None
        and any(staff_account(a) for a in accounts_for(target))
    ):
        return None
    if (
        kind == "room"
        and getattr(target or getattr(actor, "location", None), "room_type", "ic") == "ic"
    ):
        return None
    if kind not in {"page", "channel", "board", "room", "ooc"}:
        return None
    until = mute.ends_at.isoformat() if mute.ends_at else "staff lift the mute"
    return f"You are muted until {until}. You can still use +request or page staff."
