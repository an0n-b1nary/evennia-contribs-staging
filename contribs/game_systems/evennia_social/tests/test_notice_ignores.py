# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Notices use OOC boundaries independently of Boards/channel presentation."""

from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_links.ignoring import notice_ignore_status
from evennia_social import ignore


class NoticeIgnoreTests(EvenniaTest):
    """Named, full and posts exceptions block activity while staff rules persist."""

    def setUp(self):
        super().setUp()
        self.account.is_superuser = False
        self.account.permissions.clear()
        self.account2.is_superuser = False
        self.account2.permissions.clear()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_hidden_full_posts_and_account_sender_use_ooc_boundary(self):
        for level in (ignore.HIDDEN, ignore.FULL, ignore.POSTS):
            ignore.set_entry(self.char1, self.char2, level)
            self.assertEqual(notice_ignore_status(self.account, self.char2), "suppress")
            self.assertEqual(notice_ignore_status(self.account, self.account2), "suppress")
            ignore.clear(self.account)

    def test_full_covered_alt_and_posts_exception_stay_blocked(self):
        alt = create_object(type(self.char2), key="Example alt", location=self.room1)
        self.account2.characters.add(alt)
        ignore.set_entry(self.char1, self.char2, ignore.FULL)
        self.assertEqual(notice_ignore_status(self.account, alt), "suppress")
        ignore.set_entry(self.char1, alt, ignore.POSTS)
        self.assertEqual(notice_ignore_status(self.account, alt), "suppress")

    def test_staff_sender_and_viewer_keep_existing_bypass(self):
        ignore.set_entry(self.char1, self.char2)
        self.account2.permissions.add("Builder")
        self.assertEqual(notice_ignore_status(self.account, self.char2), "allow")
        self.account2.permissions.clear()
        self.account.permissions.add("Builder")
        self.assertEqual(notice_ignore_status(self.account, self.char2), "allow")
