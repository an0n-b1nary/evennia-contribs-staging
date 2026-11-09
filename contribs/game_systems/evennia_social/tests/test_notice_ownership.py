# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cached OOC policy retains live/stored owner fallback and one roster scan."""

from unittest.mock import patch

from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_links import characters
from evennia_links.ignoring import notice_ignore_status
from evennia_social import ignore


class NoticeOwnershipTests(EvenniaTest):
    """Cache behavior must match the established uncached boundary service."""

    def setUp(self):
        super().setUp()
        for account in (self.account, self.account2):
            account.is_superuser = False
            account.permissions.clear()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.staff_owner = create_account("Notice staff fallback", None, "fixture-password")
        self.staff_owner.permissions.add("Builder")
        ignore.set_entry(self.account, self.char2, ignore.FULL)

    def sender(self, key, *, roster=False, live=False, stored=False, staff=False):
        character = create_object(type(self.char2), key=key, location=self.room1)
        if roster:
            self.account2.characters.add(character)
        if live:
            character.account = self.staff_owner if staff else self.account2
        if stored:
            character.db.account = self.staff_owner if staff else self.account2
        return character

    def test_cached_and_uncached_owner_variants_match_without_repeated_roster_scans(self):
        senders = [
            self.sender("Roster only", roster=True),
            self.sender("Live only", live=True),
            self.sender("Stored only", stored=True),
            self.sender("Shared owner", roster=True, live=True),
            self.sender("Staff live fallback", roster=True, live=True, staff=True),
            self.sender("Staff stored fallback", roster=True, stored=True, staff=True),
        ]
        for legacy in (False, True):
            if legacy:
                self.account.db.ignore_entries = {}
                self.account.db.ignore_list = [self.account2.pk]
            expected = [
                "suppress" if ignore.blocks_channel(self.account, sender) else "allow"
                for sender in senders
            ]
            cache = {}
            with patch.object(
                characters, "playable_accounts", wraps=characters.playable_accounts
            ) as scans:
                for sender, outcome in zip(senders, expected, strict=True):
                    with self.subTest(sender=sender.key, legacy=legacy):
                        self.assertEqual(
                            notice_ignore_status(self.account, sender, policy_cache=cache), outcome
                        )
            self.assertEqual(scans.call_count, 1)
