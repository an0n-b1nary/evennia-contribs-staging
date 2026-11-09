# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run the same repeatable maintenance used by the daily script."""

from django.core.management.base import BaseCommand

from evennia_notices.services import maintain


class Command(BaseCommand):
    """Compact routine envelopes and remove aged acknowledged payloads."""

    help = "Recheck and maintain personal notices without touching source state."

    def handle(self, *args, **options):
        self.stdout.write(str(maintain()))
