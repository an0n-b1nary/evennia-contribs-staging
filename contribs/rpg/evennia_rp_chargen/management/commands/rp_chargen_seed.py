# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Seed the tag vocabulary and ability catalog.

    evennia rp_chargen_seed            create what's missing
    evennia rp_chargen_seed --update   also overwrite existing rows from the seed

Tags come from the ruleset; abilities from RP_CHARGEN_CATALOG_SEED. Safe to
run on every deploy.
"""

from django.core.management.base import BaseCommand, CommandError

from evennia_rp_chargen.catalog import seed_catalog


class Command(BaseCommand):
    help = "Create (or with --update, refresh) tags and catalog abilities from the seed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update", action="store_true", help="Overwrite existing rows from the seed."
        )

    def handle(self, *args, update=False, **options):
        try:
            counts = seed_catalog(update=update)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            "Tags: {tags_created} created, {tags_updated} updated. "
            "Abilities: {created} created, {updated} updated, {unchanged} unchanged.".format(
                **counts
            )
        )
