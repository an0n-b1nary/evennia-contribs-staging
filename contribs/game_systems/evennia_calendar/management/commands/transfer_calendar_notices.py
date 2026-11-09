# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Bounded idempotent Calendar source migration; never delivers offline raw text."""

import json

from django.core.management.base import BaseCommand

from evennia_calendar.notices import transfer_pending


class Command(BaseCommand):
    """Continue source migration and report held unknown legacy provenance."""

    help = "Transfer one bounded page of pending Calendar notices into the configured inbox."

    def add_arguments(self, parser):
        """Allow bounded host-controlled batches."""
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        """Report durable outcomes and continuation without deleting history."""
        result = transfer_pending(batch_size=options["batch_size"])
        self.stdout.write(json.dumps(result, sort_keys=True))
