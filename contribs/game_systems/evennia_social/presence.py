# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Presence: whether a character can be found from afar.

Each character has one visibility, stored in its ``presence_visibility``
Attribute (``SocialCharacterMixin.presence_visibility``):

- ``findable`` (default): shown wherever presence is shown.
- ``unfindable``: unlisted. Hidden from every *remote* presence surface:
  ``who``, ``+where``, ``+hangouts`` counts, a web map's who's-here and the
  public web. Any character may choose it.

Only these two visibility values are supported. A legacy stored value of
``dark`` is read as ``unfindable`` and left unchanged until the character
chooses a supported setting.

Being in the same room always reveals a character: presence is privacy from
people who aren't there, not invisibility. Staff see unfindable characters
with a marker.

Every presence surface asks this module, so the settings can't disagree:
``is_findable(character, viewer)`` for location surfaces and
``is_listed(character, viewer)`` for online lists. Web code with no
in-game viewer uses ``is_publicly_findable`` / ``is_publicly_listed``.
"""

from evennia_links.travel import room_visibility
from evennia_social.social import is_staff

FINDABLE = "findable"
UNFINDABLE = "unfindable"
VISIBILITIES = (FINDABLE, UNFINDABLE)
ATTRIBUTE = "presence_visibility"


def visibility(character):
    """The character's effective visibility: ``findable`` or ``unfindable``."""
    if character is None:
        return FINDABLE
    stored = character.attributes.get(ATTRIBUTE, default=None)
    if stored == "dark":
        return UNFINDABLE
    return stored if stored in VISIBILITIES else FINDABLE


def set_visibility(character, value):
    """
    Store a visibility.

    Raises:
        ValueError: for a value other than ``findable`` or ``unfindable``.
    """
    if value not in VISIBILITIES:
        raise ValueError(f"unknown visibility {value!r}")
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
    if _sees_through(character, viewer):
        return True
    room = getattr(character, "location", None)
    if room is not None and room_visibility(room, viewer) is False:
        return False
    return visibility(character) == FINDABLE


def is_listed(character, viewer=None):
    """Whether ``viewer`` may see that ``character`` is online at all."""
    return visibility(character) == FINDABLE or _sees_through(character, viewer)


def is_publicly_findable(character):
    """``is_findable`` for a viewer who is in no room and not staff (the public web)."""
    return is_findable(character)


def is_publicly_listed(character):
    """``is_listed`` for a viewer who is in no room and not staff (the public web)."""
    from evennia_links.guests import is_guest

    if is_guest(character):
        return False
    return visibility(character) == FINDABLE


def staff_marker(character):
    """``" (unfindable)"`` or ``""``, for staff-facing lists."""
    current = visibility(character)
    return " (unfindable)" if current == UNFINDABLE else ""
