# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_regions."""

from django.apps import AppConfig


class RegionsConfig(AppConfig):
    """AppConfig for the evennia_regions contrib.

    No ready() override: regions is a pure "answering" domain — partner
    contribs (e.g. evennia-lore's connect_soft_ref_cleanup gate) reach into
    regions, not the other way around, so there is nothing for regions
    itself to wire up.
    """

    name = "evennia_regions"
    label = "evennia_regions"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Regions"
