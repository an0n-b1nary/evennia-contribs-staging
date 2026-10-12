"""Quota changes serialize across projects owned by the same character."""

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from evennia.utils.test_resources import EvenniaTestMixin

from evennia_links.test_transactions import committed_race

from . import services
from .models import BuildProject


@override_settings(BUILDING_REVEALED=True, BUILDING_PROJECT_LIMIT=2)
class TestQuotaRace(EvenniaTestMixin, TransactionTestCase):
    def test_two_new_projects_cannot_exceed_owner_quota(self):
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Race gate runs separately with a file-backed SQLite TEST database")
        services.new_project(self.char2, "Existing proposal")
        with self.assertRaisesMessage(ValidationError, "open-project"):
            committed_race(
                lambda: services.new_project(self.char2, "Winning proposal"),
                lambda: services.new_project(self.char2, "Losing proposal"),
            )
        self.assertEqual(BuildProject.objects.filter(owner=self.char2).count(), 2)
