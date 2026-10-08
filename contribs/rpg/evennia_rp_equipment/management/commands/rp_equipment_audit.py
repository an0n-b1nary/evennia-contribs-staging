# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""`evennia rp_equipment_audit`: list worn gear whose requirements no longer hold."""

from django.core.management.base import BaseCommand

from evennia_rp_equipment.audit import problems


class Command(BaseCommand):
    help = "List worn gear whose requirements are unmet or name something the game no longer has."

    def handle(self, *args, **options):
        found = problems()
        for line in found:
            self.stdout.write(line)
        self.stdout.write(f"{len(found)} problem(s)." if found else "No problems.")
