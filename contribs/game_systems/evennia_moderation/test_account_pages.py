# SPDX-License-Identifier: BSD-3-Clause
"""Account paging policy and public sender identity, without requiring Social."""

from unittest.mock import patch

from django.test import override_settings
from evennia.comms.models import Msg
from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_moderation.commands import CmdAccountPage, CmdStaffAccountPage


class TestAccountPages(EvenniaCommandTest):
    def test_mode_markers(self):
        self.assertEqual(CmdAccountPage.comms_identity, "account")
        self.assertEqual(CmdStaffAccountPage.comms_identity, "character")

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_keeps_stock_sender_name(self):
        with patch.object(self.account2, "msg") as receive:
            self.call(CmdAccountPage(), f"{self.account2.key}=Account mode", caller=self.account)
        self.assertIn(self.account.key, str(receive.call_args.args[0]))

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_staff_pages_use_puppet_or_staff_and_keep_private_account_sender(self):
        self.account2.permissions.clear()
        self.account2.is_superuser = False
        for puppet, name in ((self.char1, self.char1.key), (None, "Staff")):
            with (
                self.subTest(name=name),
                patch.object(self.account, "get_puppet", return_value=puppet),
                patch.object(self.account2, "get_all_puppets", return_value=[self.char2]),
                patch.object(self.account2, "msg") as receive,
            ):
                output = self.call(
                    CmdStaffAccountPage(), f"{self.account2.key}=Staff contact", caller=self.account
                )
            text = strip_ansi(receive.call_args.args[0][0])
            self.assertEqual(text, f"{name} pages: Staff contact")
            self.assertNotIn(self.account.key, text)
            self.assertIn("You paged", output)
            page = Msg.objects.filter(db_message="Staff contact").latest("db_date_created")
            self.assertEqual(page.senders, [self.account])
            self.assertEqual(page.receivers, [self.account2])
            self.assertTrue(page.access(self.account2, "read"))
            for receiver in (self.account2, self.char2):
                self.assertIsNone(receiver.db.last_pager)
                self.assertEqual(receiver.db.last_pager_account, self.account.pk)

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_nonstaff_is_denied_at_lock_and_before_lookup_or_persistence(self):
        self.account2.permissions.clear()
        self.account2.is_superuser = False
        self.assertFalse(CmdStaffAccountPage().access(self.account2, "cmd"))
        with patch("evennia_moderation.commands._account") as lookup:
            output = self.call(CmdStaffAccountPage(), "Anyone=Hello", caller=self.account2)
        self.assertIn("Only moderation staff", output)
        lookup.assert_not_called()
        self.assertFalse(Msg.objects.filter(db_message="Hello").exists())

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_restrictions_apply_before_staff_page_creation(self):
        with patch("evennia_links.communication.denial", return_value="Contact denied"):
            output = self.call(
                CmdStaffAccountPage(), f"{self.account2.key}=Forbidden", caller=self.account
            )
        self.assertIn("Contact denied", output)
        self.assertFalse(Msg.objects.filter(db_message="Forbidden").exists())
