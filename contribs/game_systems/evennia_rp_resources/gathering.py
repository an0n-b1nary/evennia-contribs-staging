# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Open terrain pools and one persistent, redistributive gathering lean."""

from django.apps import apps
from django.conf import settings
from evennia.objects.models import ObjectDB

from . import conf
from .models import ResourceDefinition
from .services import ResourceError

LEAN_ATTRIBUTE = "resource_lean"


def terrain_for(room):
    provider = conf.hook("RP_RESOURCES_TERRAIN_PROVIDER")
    if provider:
        return provider(room)
    if apps.is_installed("evennia_maps"):
        from evennia_maps.terrain import resolve_terrain

        terrain = resolve_terrain(room)
        if terrain:
            return terrain
    return room.tags.get(category="terrain") or ""


def open_terrains():
    configured = getattr(settings, "RP_RESOURCES_OPEN_TERRAINS", None)
    if configured is not None:
        if callable(configured):
            configured = configured()
        elif isinstance(configured, str):
            configured = conf.hook("RP_RESOURCES_OPEN_TERRAINS")()
        return set(configured)
    # Evennia's base room typeclass and subclasses, including unmapped rooms.
    return {
        terrain
        for room in ObjectDB.objects.typeclass_search(
            settings.BASE_ROOM_TYPECLASS, include_children=True
        )
        if (terrain := terrain_for(room))
    }


def pool():
    terrains = open_terrains()
    return [
        resource
        for resource in ResourceDefinition.objects.filter(in_trickle=True, archived=False).order_by(
            "key"
        )
        if not resource.terrains or terrains.intersection(resource.terrains)
    ]


def lean(character):
    return character.attributes.get(LEAN_ATTRIBUTE, default=None)


def set_lean(character, value):
    value = value.strip().casefold()
    resources = pool()
    matches = [
        resource
        for resource in resources
        if value in (resource.key.casefold(), resource.name.casefold())
    ]
    if len(matches) == 1:
        choice = {"type": "resource", "key": matches[0].key}
    else:
        categories = [
            key
            for key, name in conf.categories().items()
            if value in (key.casefold(), name.casefold())
            and any(resource.category == key for resource in resources)
        ]
        if len(categories) != 1:
            raise ResourceError(
                "Choose a resource or category from an open terrain or the common pool."
            )
        choice = {"type": "category", "key": categories[0]}
    character.attributes.add(LEAN_ATTRIBUTE, choice)
    return choice


def lean_description(character, *, check=True):
    choice = lean(character)
    if not choice:
        return "none"
    if choice["type"] == "category":
        name = conf.categories().get(choice["key"], choice["key"])
    else:
        name = (
            ResourceDefinition.objects.filter(key=choice["key"])
            .values_list("name", flat=True)
            .first()
            or choice["key"]
        )
    if not check or any(matches_lean(resource, choice) for resource in pool()):
        return name
    return name + " (currently yields nothing)"


def matches_lean(resource, choice):
    return bool(
        choice
        and choice["key"] == (resource.key if choice["type"] == "resource" else resource.category)
    )
