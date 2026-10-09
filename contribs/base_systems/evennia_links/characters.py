# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Playable-character membership shared by every package that pays or restricts players.

Membership is the account's playable-character list (`account.characters`),
including offline characters and characters listed on more than one account.
Characters on no account (NPCs, staff-made props) belong to nobody.

The stored list is read directly rather than through each account's handler,
so a sweep never loads every account's typeclass and Attribute cache, and a
change written outside this process's identity cache is seen at once.
"""

from evennia.accounts.models import AccountDB

PLAYABLE_ATTRIBUTE = "_playable_characters"  # Evennia's CharactersHandler storage


def playable_accounts():
    """Yield `(account_id, [character, ...])`, oldest account first."""
    from evennia.utils.dbserialize import from_pickle

    rows = (
        AccountDB.objects.filter(
            db_attributes__db_key=PLAYABLE_ATTRIBUTE, db_attributes__db_category__isnull=True
        )
        .order_by("pk")
        .values_list("pk", "db_attributes__db_value")
    )
    for account_id, raw in rows:
        yield account_id, [obj for obj in from_pickle(raw) or () if obj]


def account_ids(character):
    """The ids of every account listing `character` as playable."""
    if character is None:
        return []
    return [
        account_id
        for account_id, characters in playable_accounts()
        if character.pk in {obj.pk for obj in characters}
    ]


def same_account(first, second):
    """True when some account lists both characters."""
    return bool(set(account_ids(first)) & set(account_ids(second)))


def playable_characters(predicate=None):
    """Yield each playable character once, filtered by an optional `(character) -> bool`."""
    seen = set()
    for _, characters in playable_accounts():
        for character in characters:
            if character.pk not in seen:
                seen.add(character.pk)
                if predicate is None or predicate(character):
                    yield character


def is_playable(character, predicate=None):
    """One character's membership and predicate, without sweeping the others."""
    return bool(account_ids(character)) and (predicate is None or bool(predicate(character)))
