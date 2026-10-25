# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Destination names and stable identities for generated Building exits."""

import re

from django.core.exceptions import ValidationError
from evennia.objects.models import ObjectDB

FOLLOW = "building_name_follows"
CLASH = "building_name_clash"


def validate_name(name):
    """Refuse names copied from a tagged exit display."""
    if re.match(r"^\s*<[^>]+>", name):
        raise ValidationError(
            "Name the door without a direction tag; set direction aliases instead."
        )


def aliases_for(direction):
    """Return all configured synonyms for a declared direction."""
    from .frontier import offsets

    if direction in {"in", "out", "o", "outside"}:
        return ["in"] if direction == "in" else ["out", "o", "outside"]
    value = offsets().get(direction.casefold())
    if not value or value[3] not in {"planar", "vertical"}:
        raise ValidationError("Choose a compass direction, up or down.")
    return sorted(key for key, offset in offsets().items() if offset == value)


def declared(exit):
    """Read the declared layout direction, including on a detached archived exit."""
    from .frontier import offsets

    registry = offsets()
    for name in [exit.key, *exit.aliases.all()]:
        value = registry.get(name.casefold())
        if value and value[3] in {"planar", "vertical"}:
            return name.casefold()
    return None


def canonical(value):
    """Ignore only the cosmetic name of explicitly destination-following exits.

    IDs, endpoints, aliases and locks remain part of the agreement. Explicitly
    named doors retain their reviewed names. This also works on stored JSON,
    without querying or trusting the current database to interpret a receipt.
    """
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {
            key: canonical(item)
            for key, item in value.items()
            if not (
                key == "name"
                and "follows" in value
                and value["follows"] == value.get("target")
                and "id" in value
            )
        }
    return value


def equivalent(left, right):
    """Compare preserved routes by stable identity and reviewed structure."""
    return canonical(left) == canonical(right)


def check_names(source, name, aliases=(), *, exclude=None):
    """Check every new trigger against other door names and aliases."""
    validate_name(name)
    # Several independent homes may share an anchor. Their generic 'in'
    # aliases may be ambiguous; each named entrance must still be unique.
    triggers = {value.casefold() for value in [name, *aliases] if value.casefold() != "in"}
    for exit in ObjectDB.objects.filter(db_location=source, db_destination__isnull=False).exclude(
        pk=exclude
    ):
        existing = {exit.key.casefold(), *(alias.casefold() for alias in exit.aliases.all())}
        if triggers & existing:
            raise ValidationError("That door name or direction alias is already in use.")


def follow_renames(sender, **kwargs):
    """Follow room renames without changing custom names or passage identity."""
    from .models import DraftDoor, FrontierConnection, Property

    # A rename signal also fires for exits, accounts and scripts.
    if not isinstance(sender, ObjectDB) or sender.destination or sender.location:
        return
    for exit in ObjectDB.objects.filter(db_destination=sender):
        if not exit.attributes.get(FOLLOW):
            continue
        source = exit.location
        if source is None:
            # Archived exits retain their source in the lifecycle snapshot.
            property = Property.objects.filter(entrance=exit).first()
            source = property.anchor if property else None
            if source is None:
                door = DraftDoor.objects.select_related("source__room").filter(exit=exit).first()
                source = door.source.room if door else None
            if source is None:
                connection = FrontierConnection.objects.filter(exit=exit).first()
                source = (
                    ObjectDB.objects.filter(pk=connection.data.get("source")).first()
                    if connection
                    else None
                )
        try:
            if source:
                check_names(source, sender.key, exclude=exit.pk)
            validate_name(sender.key)
        except ValidationError:
            exit.attributes.add(CLASH, sender.key)
            continue
        exit.attributes.remove(CLASH)
        exit.key = sender.key
        exit.at_cmdset_get(force_init=True)
    # Room names are independently part of a draft's exact candidate, so
    # authoring services still invalidate its version and agreements.
    # This receiver only updates the automatic door labels.


def warnings(project):
    """Report unusable labels and questionable geometry for review."""
    from .frontier import direction

    result = []
    for door in project.doors.select_related("source", "target", "exit"):
        if not door.exit:
            continue
        exit = door.exit
        if exit.attributes.get(CLASH):
            result.append(
                f"Door '{exit.key}' could not follow destination name "
                f"'{exit.attributes.get(CLASH)}': that name clashes with another door."
            )
        delta = (
            door.target.x - door.source.x,
            door.target.y - door.source.y,
            door.target.floor - door.source.floor,
        )
        label = declared(exit)
        if label and tuple(direction(label)[:3]) != delta:
            result.append(f"Door '{exit.key}' declares {label}, which disagrees with its cells.")
        if (
            delta == (0, 0, 0)
            or any(abs(value) > 1 for value in delta)
            or (delta[2] and (delta[0] or delta[1]))
        ):
            result.append(
                f"Door '{exit.key}' joins non-neighbouring rooms; it has no map-inferred direction label."
            )
    return result


def name_warnings(rooms):
    """Show a blocked automatic rename on the owning property's staff page."""
    return [
        f"Door '{exit.key}' could not follow destination name '{exit.attributes.get(CLASH)}': "
        "that name clashes with another door."
        for exit in ObjectDB.objects.filter(db_location__in=rooms, db_destination__isnull=False)
        if exit.attributes.get(CLASH)
    ]
