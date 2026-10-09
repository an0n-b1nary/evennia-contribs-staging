# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Presence: whether a character can be found from afar.

Each character has one visibility, stored in its ``presence_visibility``
Attribute (``SocialCharacterMixin.presence_visibility``):

- ``findable`` (default): shown wherever presence is shown.
- ``unfindable``: hidden from every *remote* presence surface (``+where``,
  ``+hangouts`` counts, a web map's who's-here), but still listed as online
  in ``who``. Any player may choose it.
- ``dark``: also hidden from ``who``. Staff only; a stored ``dark`` on a
  character that is no longer staff reads as ``unfindable``.

Being in the same room always reveals a character: presence is privacy from
people who aren't there, not invisibility. Staff see through both settings,
with a marker.

Every presence surface asks this module, so the settings can't disagree:
``is_findable(character, viewer)`` for location surfaces and
``is_listed(character, viewer)`` for online lists. Web code with no
in-game viewer uses ``is_publicly_findable`` / ``is_publicly_listed``.
"""

from evennia_social.social import is_staff

FINDABLE = "findable"
UNFINDABLE = "unfindable"
DARK = "dark"
VISIBILITIES = (FINDABLE, UNFINDABLE, DARK)
ATTRIBUTE = "presence_visibility"


def visibility(character):
    """The character's effective visibility: ``findable``, ``unfindable`` or ``dark``."""
    if character is None:
        return FINDABLE
    stored = character.attributes.get(ATTRIBUTE, default=None)
    if stored == DARK:
        return DARK if is_staff(character) else UNFINDABLE
    return stored if stored in VISIBILITIES else FINDABLE


def set_visibility(character, value):
    """
    Store a visibility.

    Raises:
        ValueError: for an unknown value, or ``dark`` on a non-staff character.
    """
    if value not in VISIBILITIES:
        raise ValueError(f"unknown visibility {value!r}")
    if value == DARK and not is_staff(character):
        raise ValueError("only staff can go dark")
    if value == FINDABLE:
        character.attributes.remove(ATTRIBUTE)
    else:
        character.attributes.add(ATTRIBUTE, value)


def _sees_through(character, viewer):
    if viewer is None:
        return False
    if viewer == character or is_staff(viewer):
        return True
    location = getattr(viewer, "location", None)
    return location is not None and location == getattr(character, "location", None)


def is_findable(character, viewer=None):
    """Whether ``viewer`` may see where ``character`` is."""
    return visibility(character) == FINDABLE or _sees_through(character, viewer)


def is_listed(character, viewer=None):
    """Whether ``viewer`` may see that ``character`` is online at all."""
    return visibility(character) != DARK or _sees_through(character, viewer)


def is_publicly_findable(character):
    """``is_findable`` for a viewer who is in no room and not staff (the public web)."""
    return visibility(character) == FINDABLE


def is_publicly_listed(character):
    """``is_listed`` for a viewer who is in no room and not staff (the public web)."""
    return visibility(character) != DARK


def staff_marker(character):
    """``" (unfindable)"``, ``" (dark)"`` or ``""``, for staff-facing lists."""
    current = visibility(character)
    return "" if current == FINDABLE else f" ({current})"
