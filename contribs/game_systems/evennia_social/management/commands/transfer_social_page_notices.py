# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Quietly transfer pending Social page alerts for one playable character."""

import re

from django.core.management.base import BaseCommand, CommandError
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultCharacter

from evennia_links.characters import account_ids
from evennia_links.guests import is_guest
from evennia_links.notices import NoticeContext, authorize_context

from ...notices import _active, prepare


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--character", required=True)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, character, limit, **options):
        if not 1 <= limit <= 1000:
            raise CommandError("Limit must be between 1 and 1000.")
        if not re.fullmatch(r"#[1-9][0-9]{0,17}", character):
            raise CommandError("Choose an explicit character dbref.")
        character = ObjectDB.objects.filter(pk=int(character[1:])).first()
        if not isinstance(character, DefaultCharacter) or is_guest(character):
            raise CommandError("Choose an owned, non-guest playable character.")
        context = next(
            (
                current
                for owner in AccountDB.objects.filter(pk__in=account_ids(character)).order_by("pk")
                if authorize_context(current := NoticeContext(owner, character))
            ),
            None,
        )
        if context is None:
            raise CommandError("Choose an owned, non-guest playable character.")
        if not _active():
            self.stdout.write("Social page Inbox routing is unavailable.")
            return
        counts, more = prepare(context, limit=limit)
        outcomes = ", ".join(f"{key}={count}" for key, count in sorted(counts.items()))
        self.stdout.write(
            f"{outcomes or 'No pending pages'}. More work: {'yes' if more else 'no'}."
        )
