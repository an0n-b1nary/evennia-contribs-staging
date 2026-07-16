# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Small shared helpers used across this contrib's command modules.

Kept tiny and self-contained on purpose — these are trivial enough that a
dependency on some other package would cost more than it saves.
"""

from evennia import SESSION_HANDLER
from evennia.objects.objects import DefaultCharacter
from evennia.utils.search import search_object


def is_staff(character):
    """Check if character has Builder+ permissions."""
    return character.locks.check_lockstring(character, "perm(Builder)")


def get_connected_characters():
    """Return a list of all currently connected (puppeted) characters."""
    return [s.get_puppet() for s in SESSION_HANDLER.get_sessions() if s.get_puppet()]


def find_character(name):
    """Find a single Character by name, tolerating multiple/no matches.

    Matches by isinstance(obj, DefaultCharacter) rather than a typeclass
    dotted-path string, so this works against whatever Character subclass
    the consuming game defines. On multiple matches, prefers an exact
    (case-insensitive) key match if there is exactly one.

    Returns:
        tuple: (character_or_none, error_message_or_none). error_message
        is a ready-to-display string ("Could not find 'X'." or
        "Multiple matches for 'X': ...") when character is None.
    """
    if not name:
        return None, "You must specify a character name."

    matches = [obj for obj in search_object(name) if isinstance(obj, DefaultCharacter)]
    if not matches:
        return None, f"Could not find '{name}'."
    if len(matches) > 1:
        exact = [m for m in matches if m.key.lower() == name.lower()]
        if len(exact) == 1:
            matches = exact
        else:
            names = ", ".join(m.key for m in matches)
            return None, f"Multiple matches for '{name}': {names}."
    return matches[0], None
