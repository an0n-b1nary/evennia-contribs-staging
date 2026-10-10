# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Host typeclass modules import this contrib before Evennia fills its flat API."""

import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

# A management command such as `evennia check` imports the URLconf, whose forms
# load the host's object typeclass, before `evennia.DefaultObject` is set.
SCRIPT = """
import django
django.setup()
import evennia
assert evennia.DefaultObject is None, "flat API already initialised"
from evennia_economy.typeclasses import EconomyObjectMixin, StallStock
print("imported")
"""


class CliImportTests(SimpleTestCase):
    def test_typeclasses_import_while_the_flat_api_is_unset(self):
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT],
            cwd=settings.GAME_DIR,
            # The launcher puts the settings directory on the path; mirror it.
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": settings.SETTINGS_MODULE,
                "PYTHONPATH": os.pathsep.join(path for path in sys.path if path),
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("imported", result.stdout)
