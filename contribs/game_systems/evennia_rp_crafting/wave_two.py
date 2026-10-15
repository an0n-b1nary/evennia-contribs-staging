# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reusable authored modes and fixed room cosmetics; neither carries mechanics."""

import random
from collections import Counter
from datetime import timedelta

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from evennia_links.rooms import is_live
from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import conf
from .behaviours import Behaviour, text
from .emissions import emit, frame
from .errors import CraftingError
from .models import ActivationUse, CraftRecord, FixtureInstallation


def line(value, label="EVENT line"):
    value = text(value, label, 400, required=True)
    if not value.isprintable() or "|" in value or "<EVENT>" in value:
        raise CraftingError("EVENT lines must be plain, single-line prose.")
    return value


class Installable(Behaviour):
    fields = ("room_line", "smell", "sound", "ambient")
    typeclass = "evennia_rp_crafting.typeclasses.Installable"
    typeclass_setting = "RP_CRAFTING_INSTALLABLE_TYPECLASS"

    def validate(self, config):
        config = super().validate(config)
        result = {key: text(config.get(key, ""), key, 400) for key in self.fields}
        if not any(result.values()):
            raise CraftingError("Give the fixture a room, smell, sound or ambient line.")
        if result["ambient"]:
            result["ambient"] = line(result["ambient"])
            if not apps.is_installed("evennia_accessibility"):
                raise CraftingError("Ambient fixtures require the accessibility partner.")
        return result


class Activatable(Behaviour):
    role = "verb"
    fields = ("modes",)

    def validate(self, config):
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_slug

        config = super().validate(config)
        modes = config.get("modes")
        if not isinstance(modes, dict) or not 1 <= len(modes) <= 8:
            raise CraftingError("Choose 1-8 named activation modes.")
        result = {}
        for key, readings in modes.items():
            try:
                if not isinstance(key, str) or len(key) > 40:
                    raise ValueError
                validate_slug(key)
            except (ValidationError, ValueError) as exc:
                raise CraftingError("Mode names must be short stable keys.") from exc
            if not isinstance(readings, list) or not 1 <= len(readings) <= 20:
                raise CraftingError("Each mode needs 1-20 authored readings.")
            result[key] = [line(reading) for reading in readings]
        return {"modes": result}

    def cost(self, key, config):
        from django.conf import settings

        rules = getattr(settings, "RP_CRAFTING_COSTS", conf.DEFAULT_COSTS).get(key, {})
        from .catalog import category_cost

        if "extra_mode" not in rules or "extra_reading" not in rules:
            raise CraftingError("This behaviour has no extra-mode or extra-reading cost rule.")
        total = Counter(super().cost(key, config))
        for _ in range(len(config["modes"]) - 1):
            total.update(category_cost(rules["extra_mode"]))
        for readings in config["modes"].values():
            for _ in readings[1:]:
                total.update(category_cost(rules["extra_reading"]))
        if sum(total.values()) > conf.MAX_AMOUNT:
            raise CraftingError("Activation costs exceed the supported range.")
        return dict(total)

    def invoke(self, actor, item, configuration):
        return activate(actor, item, next(iter(configuration["modes"])))


@atomic_objects
def activate(actor, item, mode=None):
    from .fixtures import _lock, reserve_event

    room = actor.location
    if room is None:
        raise CraftingError("Use the item in an active room.")
    actor, room, item = _lock(actor, room, item)
    if not is_live(room):
        raise CraftingError("Use the item in an active room.")
    placement = FixtureInstallation.objects.filter(craft__item_id=item.pk, active=True).first()
    if placement:
        allowed = placement.room_id == room.pk and item.location == room
    else:
        allowed = item.location == actor
    if record_is_companion := CraftRecord.objects.filter(
        item_id=item.pk, behaviour="companion"
    ).exists():
        from .companions import _require

        _require(actor, item)
        allowed = item.location in (actor, room)
    if not allowed or not item.access(actor, "use", default=True):
        raise CraftingError(
            "Carry the item or visit its installation, and have permission to use it."
        )
    record = CraftRecord.objects.filter(item_id=item.pk).first()
    entry = (
        next((entry for entry in record.verb_data if entry["key"] == "activatable"), None)
        if record
        else None
    )
    if not entry:
        raise CraftingError("This item has no activation modes.")
    modes = entry["configuration"]["modes"]
    mode = mode or next(iter(modes))
    if mode not in modes:
        raise CraftingError(f"Available modes: {', '.join(modes)}.")
    now = timezone.now()
    previous = ActivationUse.objects.filter(craft=record).order_by("-created_at", "-pk").first()
    if previous and now < previous.created_at + timedelta(
        seconds=get("RP_CRAFTING_ACTIVATION_ITEM_COOLDOWN")
    ):
        raise CraftingError("This item was just used. Wait a moment before using it again.")
    reserve_event(room, now)
    message = frame(random.choice(modes[mode]))
    use = ActivationUse.objects.create(
        craft=record, actor_id=actor.pk, room_id=room.pk, mode=mode, message=message
    )
    # Tricks honour ambient mute when Accessibility can supply it; without that
    # partner they are ordinary owner-triggered events rather than dropped.
    mutable = record_is_companion and apps.is_installed("evennia_accessibility")
    transaction.on_commit(
        lambda: emit(room.pk, actor.pk, message, ambient=mutable, wave_three=record_is_companion)
    )
    return use
