# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Import one bounded page of Lore pending events without printing private text."""

from django.core.management.base import BaseCommand, CommandError

from evennia_lore.notices import transfer_pending


class Command(BaseCommand):
    """Transfer known events; preserve and count ambiguous historical rows."""

    help = "Route one bounded page of Lore notices; repeat while continuation remains."

    def add_arguments(self, parser):
        """Accept a bounded page size only."""
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        """Report dispositions without private subjects, actors or messages."""
        try:
            counts = transfer_pending(limit=options["limit"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            "Lore transfer: " + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
