# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Making, editing, wearing and removing equipment: the API commands (and games) call.

Each function raises `GearError` with a message fit to show the player. The rules:

- **Making.** Anyone can make a plain item, up to `RP_EQUIPMENT_ITEM_CAP`
  items of their making in the world at once.
- **Editing.** Only the maker changes an item's prose, slot and requirements,
  and only until a character other than the maker has held it ("sealed").
  Requirements can't change while the item is worn.
- **Wearing.** Every requirement must be met, except that an ability the
  wearer doesn't own only earns a "not fully attuned" notice. Wearing and
  removing are frozen whenever the build is (`evennia_rp_chargen.locks.frozen`).
- **Staying put.** A worn item can't be dropped, given or destroyed; remove it
  first. The build changes worn gear depends on are refused by `guard`.
"""

from __future__ import annotations

from evennia.utils.create import create_object

from evennia_rp_equipment import conf
from evennia_rp_equipment.display import is_equipment
from evennia_rp_equipment.requirements import (
    UNATTUNED,
    UNKNOWN,
    UNMET,
    Requirement,
    RequirementError,
    describe,
    parse,
    status,
)
from evennia_rp_equipment.typeclasses import MAKER_CATEGORY, TAG_CATEGORY, WORN_TAG

MAX_NAME = 80
MAX_SLOT = 30
MAX_WORN_LINE = 200


class GearError(Exception):
    """A gear change isn't allowed. The message is fit to show the player."""


def _name(item, looker) -> str:
    return item.get_display_name(looker)


def _check_held(character, item) -> None:
    if not is_equipment(item):
        raise GearError(f"{_name(item, character)} isn't something you can wear.")
    if item.location != character:
        raise GearError(f"You aren't carrying {_name(item, character)}.")


def _check_editable(character, item) -> None:
    _check_held(character, item)
    if item.maker_id != character.id:
        raise GearError(f"Only its maker can change {_name(item, character)}.")
    if item.sealed:
        raise GearError(f"{_name(item, character)} has changed hands, so it's fixed now.")


def _check_unfrozen(character) -> None:
    from evennia_rp_chargen import locks

    if locks.frozen(character):
        raise GearError(locks.locked_message())


# ---------------------------------------------------------------------------
# Making and editing
# ---------------------------------------------------------------------------


def made_count(character) -> int:
    """Items of `character`'s making still in the world."""
    from evennia.objects.models import ObjectDB

    return ObjectDB.objects.get_by_tag(str(character.id), category=MAKER_CATEGORY).count()


def make(character, name: str, *, slot: str = ""):
    """A new plain item in `character`'s hands, made by them."""
    name = (name or "").strip()
    if not name:
        raise GearError("Give the item a name.")
    if len(name) > MAX_NAME:
        raise GearError(f"Keep the name to {MAX_NAME} characters.")
    slot = _clean_slot(slot)
    cap = conf.item_cap()
    if cap is not None and made_count(character) >= cap:
        raise GearError(
            f"You already have {cap} items of your making in the world, the most allowed. "
            "Destroy one first."
        )
    item = create_object(
        conf.get("RP_EQUIPMENT_TYPECLASS"), key=name, location=character, home=character
    )
    item.maker_id = character.id
    item.maker_name = character.key
    item.slot = slot
    item.sealed = False  # creation moves it into the maker's hands before maker_id is set
    item.tags.add(str(character.id), category=MAKER_CATEGORY)
    return item


def _clean_slot(slot: str) -> str:
    slot = (slot or "").strip().lower()
    if len(slot) > MAX_SLOT:
        raise GearError(f"Keep the slot to {MAX_SLOT} characters.")
    return slot


def set_desc(character, item, text: str) -> None:
    _check_editable(character, item)
    item.db.desc = (text or "").strip()


def set_worn_line(character, item, text: str) -> None:
    _check_editable(character, item)
    text = (text or "").strip()
    if len(text) > MAX_WORN_LINE:
        raise GearError(f"Keep the worn line to {MAX_WORN_LINE} characters.")
    item.worn_line = text


def set_slot(character, item, slot: str) -> None:
    _check_editable(character, item)
    item.slot = _clean_slot(slot)


def add_requirement(character, item, text: str) -> Requirement:
    """Add a requirement; one on the same stat and kind replaces the old one."""
    _check_editable(character, item)
    if item.is_worn:
        raise GearError(f"Remove {_name(item, character)} before changing what it requires.")
    try:
        req = parse(text)
    except RequirementError as exc:
        raise GearError(str(exc)) from None
    current = item.get_requirements()
    if req in current:
        raise GearError(f"{_name(item, character)} already requires {describe(req)}.")
    if req.on_stat:
        current = [r for r in current if (r.kind, r.stat) != (req.kind, req.stat)]
    item.requirement_data = [r.to_dict() for r in [*current, req]]
    return req


def remove_requirement(character, item, number: int) -> Requirement:
    """Remove requirement `number` (1-based, as `+gear/info` lists them)."""
    _check_editable(character, item)
    if item.is_worn:
        raise GearError(f"Remove {_name(item, character)} before changing what it requires.")
    current = item.get_requirements()
    if not 1 <= number <= len(current):
        raise GearError(f"{_name(item, character)} has no requirement {number}.")
    removed = current.pop(number - 1)
    item.requirement_data = [r.to_dict() for r in current]
    return removed


def destroy(character, item) -> str:
    """Destroy an item you carry. Returns its name."""
    _check_held(character, item)
    if item.is_worn:
        raise GearError(f"Remove {_name(item, character)} first.")
    name = _name(item, character)
    item.delete()
    return name


# ---------------------------------------------------------------------------
# Wearing
# ---------------------------------------------------------------------------


def report(character, item) -> list[tuple[Requirement, str]]:
    """Each requirement with its status for `character`."""
    return [(req, status(character, req)) for req in item.get_requirements()]


def _announce(character, room_text: str, item) -> None:
    location = character.location
    if location is not None:
        location.msg_contents(
            room_text,
            exclude=[character],
            mapping={"actor": character, "item": item},
            from_obj=character,
        )


def wear(character, item) -> list[str]:
    """Put an item on. Returns notices (abilities it isn't fully attuned to)."""
    _check_held(character, item)
    if item.is_worn:
        raise GearError(f"You're already wearing {_name(item, character)}.")
    _check_unfrozen(character)
    results = report(character, item)
    unknown = [describe(r) for r, s in results if s == UNKNOWN]
    if unknown:
        raise GearError(
            f"Wearing {_name(item, character)} requires something this game no longer has "
            f"({', '.join(unknown)}). Ask staff."
        )
    unmet = [describe(r) for r, s in results if s == UNMET]
    if unmet:
        raise GearError(f"Wearing {_name(item, character)} needs {', '.join(unmet)}.")
    item.tags.add(WORN_TAG, category=TAG_CATEGORY)
    character.msg(f"You put on {_name(item, character)}.")
    _announce(character, "{actor} puts on {item}.", item)
    return [
        f"You aren't fully attuned to {_name(item, character)}; full attunement needs {describe(r)}."
        for r, s in results
        if s == UNATTUNED
    ]


def remove(character, item) -> None:
    """Take an item off."""
    _check_held(character, item)
    if not item.is_worn:
        raise GearError(f"You aren't wearing {_name(item, character)}.")
    _check_unfrozen(character)
    item.tags.remove(WORN_TAG, category=TAG_CATEGORY)
    character.msg(f"You take off {_name(item, character)}.")
    _announce(character, "{actor} takes off {item}.", item)


__all__ = [
    "GearError",
    "add_requirement",
    "destroy",
    "made_count",
    "make",
    "remove",
    "remove_requirement",
    "report",
    "set_desc",
    "set_slot",
    "set_worn_line",
    "wear",
]
