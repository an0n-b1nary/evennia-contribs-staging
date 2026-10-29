# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The shared test bases keep their account options to their own classes.

A host game runs these bases under its own settings. Changing the host's
options would break whichever test class happens to run next.
"""

import unittest

from django.conf import settings
from django.test import TestCase, override_settings

from evennia_social.tests.base import _ACCOUNT_OPTIONS, SocialCommandTestCase, SocialTestCase

_HOST_SEPARATOR = ("Host separator.", "BaseOption", "")


class TestAccountOptionScope(TestCase):
    def test_host_options_win_and_survive_the_class(self):
        for base in (SocialTestCase, SocialCommandTestCase):
            with self.subTest(base=base.__name__):

                class Probe(base):
                    seen = {}  # noqa: RUF012 — collects what the probe saw

                    def test_reads_options(self):
                        self.seen.update(settings.OPTIONS_ACCOUNT_DEFAULT)

                host = {"pose_separator": _HOST_SEPARATOR}
                result = unittest.TestResult()
                with override_settings(OPTIONS_ACCOUNT_DEFAULT=host):
                    unittest.TestSuite([Probe("test_reads_options")]).run(result)
                    after = settings.OPTIONS_ACCOUNT_DEFAULT

                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assertEqual(Probe.seen["pose_separator"], _HOST_SEPARATOR)
                self.assertEqual(
                    Probe.seen["highlight_enabled"], _ACCOUNT_OPTIONS["highlight_enabled"]
                )
                self.assertEqual(after, {"pose_separator": _HOST_SEPARATOR})
