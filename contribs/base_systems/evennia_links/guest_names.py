# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Readable disposable character names; account usernames stay unchanged."""

import random

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

ADJECTIVES = (
    "Ambling",
    "Bright",
    "Curious",
    "Dancing",
    "Dappled",
    "Gentle",
    "Golden",
    "Happy",
    "Leaping",
    "Little",
    "Merry",
    "Quiet",
    "Silver",
    "Sunny",
    "Wandering",
    "Wild",
)
ANIMALS = (
    "Badger",
    "Deer",
    "Dolphin",
    "Finch",
    "Fox",
    "Heron",
    "Hare",
    "Lark",
    "Lynx",
    "Otter",
    "Owl",
    "Panda",
    "Robin",
    "Seal",
    "Sparrow",
    "Wren",
)
NAME_ATTEMPTS = 5


def default_guest_name():
    """Generate an adjective and an animal, using Python's random source."""
    return f"{random.choice(ADJECTIVES)} {random.choice(ANIMALS)}"


def guest_character_name():
    """Choose a name unused by any DefaultCharacter subclass, ignoring case.

    EVENNIA_GUEST_NAME_GENERATOR accepts a zero-argument callable or its dotted
    import path. After five clashes, number the final candidate, checking each
    suffix too. Deleting a guest naturally frees its name for later visits.
    """
    from evennia.objects.models import ObjectDB
    from evennia.objects.objects import DefaultCharacter

    generator = getattr(settings, "EVENNIA_GUEST_NAME_GENERATOR", default_guest_name)
    if isinstance(generator, str):
        try:
            generator = import_string(generator)
        except ImportError as exc:
            raise ImproperlyConfigured("Cannot import EVENNIA_GUEST_NAME_GENERATOR.") from exc
    if not callable(generator):
        raise ImproperlyConfigured("EVENNIA_GUEST_NAME_GENERATOR must be callable.")

    def exists(name):
        # Loading matching objects resolves even persisted typeclasses that
        # have not yet been imported in this server process. filter_family()
        # only knows subclasses already loaded, so it can miss those names.
        return any(
            isinstance(obj, DefaultCharacter)
            for obj in ObjectDB.objects.filter(db_key__iexact=name)
        )

    for _ in range(NAME_ATTEMPTS):
        name = generator()
        if not isinstance(name, str) or not name.strip():
            raise ImproperlyConfigured("EVENNIA_GUEST_NAME_GENERATOR must return a nonempty name.")
        # Character.create() normalizes the key; check the name it will store.
        name = DefaultCharacter.normalize_name(name.strip())
        if not exists(name):
            return name
    number = 2
    while exists(candidate := f"{name} {number}"):
        number += 1
    return candidate
