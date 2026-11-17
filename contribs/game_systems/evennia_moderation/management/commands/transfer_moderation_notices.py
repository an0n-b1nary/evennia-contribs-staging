# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Transfer one bounded page of known account outcomes, preserving history."""

from django.core.management.base import BaseCommand, CommandError
from evennia.accounts.models import AccountDB

from evennia_moderation.notices import transfer_pending


class Command(BaseCommand):
    """Safe repeatable source migration with disposition counts only."""

    help = "Transfer a bounded page of pending Moderation outcomes; unknown provenance stays held."

    def add_arguments(self, parser):
        parser.add_argument("--account", type=int)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        account = None
        if options["account"] is not None:
            account = AccountDB.objects.filter(pk=options["account"]).first()
            if account is None:
                raise CommandError("Account not found")
        try:
            counts = transfer_pending(account, limit=options["limit"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("; ".join(f"{key}: {value}" for key, value in counts.items()))
