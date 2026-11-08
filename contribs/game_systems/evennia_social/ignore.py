# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Personal boundaries shared by communication and gameplay consumers.

Named entries live in ``account.db.ignore_entries``, keyed by character id.
Each records a level, the named character's name, and (for full ignores) the
account ids covered when it was made. The old ``ignore_list`` remains a list
of earlier full ignores: it has no named removal path. Reading it lazily
preserves protection without a database migration or an alt-name oracle.
"""

import logging
from collections.abc import Mapping

from django.db import transaction
from evennia.accounts.models import AccountDB

from evennia_links.characters import account_ids
from evennia_links.ignoring import notify_ignore_policy_changing

logger = logging.getLogger("evennia")

NONE = "none"
POSTS = "posts"
HIDDEN = "hidden"
FULL = "full"
PREFERENCES = "ignore_preferences"
SHOW = "show"
HIDE = "hide"


class PolicyChangeError(Exception):
    """Required pre-change bookkeeping failed; the policy transaction rolled back."""


def account_for(actor):
    """The viewer's account, including offline characters."""
    if isinstance(actor, AccountDB):
        return actor
    return (getattr(actor, "account", None) or actor.db.account) if actor else None


def owners(actor):
    """All playable owners, plus the live/stored owner used by host fixtures."""
    if isinstance(actor, AccountDB):
        return {actor.pk}
    ids = set(account_ids(actor))
    if account := account_for(actor):
        ids.add(account.pk)
    return ids


def _staff(ids):
    return any(
        account.is_superuser or account.check_permstring("Builder")
        for account in AccountDB.objects.filter(pk__in=ids)
    )


def entries(viewer):
    account = account_for(viewer)
    return dict(account.db.ignore_entries or {}) if account else {}


def earlier(viewer):
    account = account_for(viewer)
    return set(account.db.ignore_list or []) if account else set()


def _preferences(account):
    value = getattr(account.db, PREFERENCES)
    return dict(value) if isinstance(value, Mapping) else {}


def _presentation_preference(viewer, kind):
    account = account_for(viewer)
    if not account:
        return SHOW
    value = _preferences(account).get(kind, SHOW)
    return value if value in (SHOW, HIDE) else SHOW


def boards_preference(viewer):
    """Return this account's board policy: ``show`` (placeholder) or ``hide``."""
    return _presentation_preference(viewer, "boards")


def channels_preference(viewer):
    """Return the account-shared preference for both IC and OOC channels."""
    return _presentation_preference(viewer, "channels")


def _before_policy_change(account, kind=None):
    try:
        notify_ignore_policy_changing(account, kind)
    except Exception as exc:
        logger.exception("Social ignore policy bookkeeping failed")
        raise PolicyChangeError from exc


@transaction.atomic
def _set_presentation_preference(viewer, preference, kind):
    if preference not in (SHOW, HIDE):
        raise ValueError("Ignore preference must be 'show' or 'hide'.")
    account = account_for(viewer)
    if not account:
        raise ValueError("You must be logged in to use this command.")
    _locked(account)
    preferences = _preferences(account)
    changed = _presentation_preference(account, kind) != preference
    if changed:
        _before_policy_change(account, kind)
    preferences[kind] = preference
    setattr(account.db, PREFERENCES, preferences)
    return changed


def set_boards_preference(viewer, preference):
    """Set the account-shared board preference, preserving other preference keys."""
    return _set_presentation_preference(viewer, preference, "boards")


def set_channels_preference(viewer, preference):
    """Set the account-shared IC/OOC channel preference, preserving other keys."""
    return _set_presentation_preference(viewer, preference, "channels")


def named_entry(viewer, character):
    return entries(viewer).get(character.pk) if character else None


def ignore_level(viewer, character):
    """Return none, posts (visible posts, blocked contact), or hidden.

    A character entry overrides full ignores. Staff senders always bypass
    filtering, including offline playable staff characters.
    """
    account = account_for(viewer)
    if not account or not character or viewer == character:
        return NONE
    named, old = entries(account), earlier(account)
    # Every delivery asks; owners() sweeps all accounts, so skip it when empty.
    if not named and not old:
        return NONE
    ids = owners(character)
    if not isinstance(character, AccountDB) and (entry := named.get(character.pk)):
        level = POSTS if entry["level"] == POSTS else HIDDEN
    elif ids & old or any(
        entry["level"] == FULL and ids.intersection(entry["accounts"]) for entry in named.values()
    ):
        level = HIDDEN
    else:
        return NONE
    return NONE if _staff(ids) else level


def blocks_channel(viewer, sender):
    """OOC lines stay filtered even for characters whose posts are excepted.

    Channels address the player: any named boundary on that player's
    characters covers their OOC channel lines in either communication mode.
    """
    if not sender or viewer == sender:
        return False
    named, old = entries(viewer), earlier(viewer)
    if not named and not old:
        return False
    ids = owners(sender)
    covered = bool(ids & old) or any(
        ids.intersection(entry["accounts"]) for entry in named.values()
    )
    return covered and not _staff(ids)


def _locked(account):
    AccountDB.objects.select_for_update().get(pk=account.pk)
    account.attributes.reset_cache()


@transaction.atomic
def set_entry(viewer, character, level=HIDDEN):
    """Set only this named entry; return whether it changed."""
    if level not in (HIDDEN, POSTS, FULL):
        raise ValueError("Unknown ignore level.")
    account = account_for(viewer)
    if not account:
        raise ValueError("You must be logged in to use this command.")
    if viewer == character or account == account_for(character):
        raise ValueError("You can't ignore yourself.")
    ids = owners(character)
    if not ids:
        raise ValueError("Could not determine that character's account.")
    _locked(account)
    named = entries(account)
    previous = named.get(character.pk)
    current = {"name": character.key, "level": level, "accounts": sorted(ids)}
    changed = previous != current
    if previous is None or any(previous.get(key) != current[key] for key in ("level", "accounts")):
        _before_policy_change(account)
    named[character.pk] = current
    account.db.ignore_entries = named
    return changed


@transaction.atomic
def remove_entry(viewer, character):
    """Remove only the named entry, returning it or None; never infer an alt."""
    account = account_for(viewer)
    if not account or character is None:
        return None
    _locked(account)
    named = entries(account)
    entry = named.pop(character.pk, None)
    if entry is not None:
        _before_policy_change(account)
    account.db.ignore_entries = named
    return entry


@transaction.atomic
def clear(viewer):
    account = account_for(viewer)
    if not account:
        return 0
    _locked(account)
    count = len(entries(account)) + len(earlier(account))
    if count:
        _before_policy_change(account)
    account.db.ignore_entries = {}
    account.db.ignore_list = []
    return count
