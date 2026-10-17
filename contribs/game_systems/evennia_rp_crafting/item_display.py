# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Craft-owned presentation through Equipment's optional public display seam."""

from django.apps import apps


def equipment_renders(item):
    if apps.is_installed("evennia_rp_equipment"):
        from evennia_rp_equipment.typeclasses import EquipmentMixin

        return isinstance(item, EquipmentMixin)
    return False


def state(item, looker, context, text):
    from .states import variant

    selected = variant(item)
    return selected.get("description" if context == "desc" else "worn_line", text)


def layers(item, looker, context, text):
    from .modifiers import display

    extra = display(item)
    if extra:
        text = f"{text}\n\n{extra}" if context == "desc" else f"{text}\n  {extra}"
    return text


def render(item, looker, context, text):
    return layers(item, looker, context, state(item, looker, context, text))
