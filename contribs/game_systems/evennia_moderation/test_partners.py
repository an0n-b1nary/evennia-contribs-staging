# SPDX-License-Identifier: BSD-3-Clause
"""Fresh-process absence is checked by the dedicated partner gate."""

from importlib.util import find_spec
from unittest import skipUnless

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase


@skipUnless(hasattr(settings, "MODERATION_ABSENT_PARTNERS"), "Dedicated partner gate")
class TestPhysicalAbsence(SimpleTestCase):
    def test_absent_packages_are_not_importable_or_registered(self):
        for label in settings.MODERATION_ABSENT_PARTNERS:
            with self.subTest(partner=label):
                self.assertIsNone(find_spec(label))
                self.assertFalse(apps.is_installed(label))
