# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Private, named sets of worn item IDs; applying a set replaces all worn gear.

Only items currently carried by the caller can be resolved. Stale references
never summon items or expose another holder's inventory. No crafting required.
"""

from __future__ import annotations

from django.db import transaction

from evennia_rp_equipment import services
from evennia_rp_equipment.display import is_equipment, worn_items
from evennia_rp_equipment.services import MAX_NAME, GearError
from evennia_rp_equipment.typeclasses import TAG_CATEGORY, WORN_TAG

ATTRIBUTE = "outfits"


def _name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > MAX_NAME:
        raise GearError(f"Give the outfit a name of 1 to {MAX_NAME} characters.")
    return name


def saved(character) -> dict:
    """A copy of the character's saved sets, keyed by case-insensitive name."""
    data = character.attributes.get(ATTRIBUTE, category=TAG_CATEGORY, default={})
    return {
        key: {"name": value["name"], "items": list(value["items"])} for key, value in data.items()
    }


def save(character, name: str) -> None:
    """Save (or replace) a named set with everything currently worn, even covered gear."""
    name = _name(name)
    data = saved(character)
    data[name.casefold()] = {"name": name, "items": [item.id for item in worn_items(character)]}
    character.attributes.add(ATTRIBUTE, data, category=TAG_CATEGORY)


def get(character, name: str) -> dict:
    name = _name(name)
    try:
        return saved(character)[name.casefold()]
    except KeyError:
        raise GearError(f"You have no outfit named {name}.") from None


def delete(character, name: str) -> None:
    outfit = get(character, name)
    data = saved(character)
    del data[outfit["name"].casefold()]
    character.attributes.add(ATTRIBUTE, data, category=TAG_CATEGORY)


def items(character, name: str) -> list[tuple[int, object | None]]:
    """Saved IDs paired with carried gear, or None for missing/transferred/deleted items."""
    carried = {item.id: item for item in character.contents if is_equipment(item)}
    return [(pk, carried.get(pk)) for pk in get(character, name)["items"]]


def apply(character, name: str) -> list[str]:
    """Replace worn gear after validating the whole set. Return attunement notices.

    All writes succeed together. Messages follow successful writes, so a refused
    outfit leaves no partial change or misleading room announcement.
    """
    outfit = get(character, name)
    services._check_unfrozen(character)
    references = items(character, name)
    missing = [f"#{pk}" for pk, item in references if item is None]
    if missing:
        raise GearError(
            f"Outfit {outfit['name']} needs items you no longer carry: {', '.join(missing)}."
        )
    target = [item for _, item in references]
    notices = []
    for item in target:
        notices.extend(services.check_wear_requirements(character, item))
    current = worn_items(character)
    removing = [item for item in current if item not in target]
    adding = [item for item in target if item not in current]
    changed = [*removing, *adding]
    try:
        with transaction.atomic():
            for item in removing:
                item.tags.remove(WORN_TAG, category=TAG_CATEGORY)
            for item in adding:
                item.tags.add(WORN_TAG, category=TAG_CATEGORY)
    except Exception:
        # TagHandlers cache writes immediately, including writes rolled back by Django.
        for item in changed:
            item.tags.reset_cache()
        raise
    character.msg(f"You change into outfit {outfit['name']}.")
    if character.location is not None:
        character.location.msg_contents(
            "{actor} changes outfits.",
            exclude=[character],
            mapping={"actor": character},
            from_obj=character,
        )
    return notices
