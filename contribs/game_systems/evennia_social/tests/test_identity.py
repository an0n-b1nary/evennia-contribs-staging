# SPDX-License-Identifier: BSD-3-Clause
from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_social.identity import staff_run_marker


@override_settings(SOCIAL_STAFF_RUN_MARKER=True)
class TestStaffIdentity(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.account.is_superuser = False
        self.account.save()
        self.account.permissions.clear()
        self.account.permissions.add("Builder")
        self.account.characters.add(self.char1)
        self.char1.account = None

    def test_offline_roster_and_quelling_do_not_hide_marker(self):
        self.account.db._quell = True
        self.assertEqual(staff_run_marker(self.char1), " (staff-run)")

    def test_marker_tracks_current_permission_without_exposing_owner(self):
        self.assertEqual(staff_run_marker(self.char1), " (staff-run)")
        self.account.permissions.clear()
        self.account.permissions.add("Player")
        self.assertEqual(staff_run_marker(self.char1), "")

    def test_higher_permission_also_marks_staff(self):
        self.account.permissions.clear()
        self.account.permissions.add("Developer")
        self.assertEqual(staff_run_marker(self.char1), " (staff-run)")

    @override_settings(SOCIAL_STAFF_RUN_MARKER=False)
    def test_default_opt_out(self):
        self.assertEqual(staff_run_marker(self.char1), "")
