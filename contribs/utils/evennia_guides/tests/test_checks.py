# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Named checks and staff: resolution order, failing closed."""

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_guides import checks

PASSING = "evennia_guides.tests.test_checks.always"


def always():
    return True


def boom():
    raise RuntimeError("broken check")


class TestResolution(SimpleTestCase):
    def tearDown(self):
        checks._registry.pop("guides.test", None)

    def test_host_override_bool_callable_and_dotted_path(self):
        with override_settings(GUIDES_CHECKS={"A": True, "B": lambda: False, "C": PASSING}):
            self.assertTrue(checks.check("A"))
            self.assertFalse(checks.check("B"))
            self.assertTrue(checks.check("C"))

    def test_registered_check(self):
        checks.register_check("guides.test", lambda: True)
        self.assertTrue(checks.check("guides.test"))
        with override_settings(GUIDES_CHECKS={"guides.test": False}):
            self.assertFalse(checks.check("guides.test"))  # the host wins

    def test_django_setting(self):
        with override_settings(GUIDES_TEST_SWITCH=True):
            self.assertTrue(checks.check("GUIDES_TEST_SWITCH"))
            self.assertTrue(checks.is_known("GUIDES_TEST_SWITCH"))

    def test_unknown_and_broken_checks_fail_closed(self):
        self.assertFalse(checks.is_known("GUIDES_NO_SUCH_SWITCH"))
        with self.assertLogs("evennia", "WARNING"):
            self.assertFalse(checks.check("GUIDES_NO_SUCH_SWITCH_2"))
        with override_settings(GUIDES_CHECKS={"X": boom}), self.assertLogs("evennia", "ERROR"):
            self.assertFalse(checks.check("X"))

    def test_register_needs_a_callable(self):
        with self.assertRaises(TypeError):
            checks.register_check("guides.test", True)


class TestRuntimeSetting(EvenniaTest):
    """A links runtime setting follows a staff change without a restart."""

    def test_runtime_setting(self):
        try:
            from evennia_links import runtime
        except ImportError:
            self.skipTest("evennia_links isn't installed")
        runtime.register(
            "GUIDES_TEST_RUNTIME", False, validator=lambda v: isinstance(v, bool), description=""
        )
        self.assertFalse(checks.check("GUIDES_TEST_RUNTIME"))
        runtime.set("GUIDES_TEST_RUNTIME", True)
        self.assertTrue(checks.check("GUIDES_TEST_RUNTIME"))


class TestIsStaff(EvenniaTest):
    def test_viewers(self):
        self.assertFalse(checks.is_staff(None))
        self.assertFalse(checks.is_staff(AnonymousUser()))
        self.assertFalse(checks.is_staff(self.account2))
        self.account2.permissions.add("Admin")
        self.assertTrue(checks.is_staff(self.account2))

    def test_the_lock_is_a_setting(self):
        self.account2.permissions.add("Builder")
        self.assertFalse(checks.is_staff(self.account2))
        with override_settings(GUIDES_STAFF_LOCK="perm(Builder)"):
            self.assertTrue(checks.is_staff(self.account2))
