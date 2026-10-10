# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""`evennia guides_check`: report guide pages that were skipped or look wrong."""

from django.core.management.base import BaseCommand, CommandError

from evennia_guides.pages import all_pages, validate


class Command(BaseCommand):
    help = (
        "Check every guide page: files that failed to load, links and principle tags "
        "that name no page, checks that resolve to nothing, and replaced pages."
    )

    def handle(self, *args, **options):
        problems = validate()
        for level, source, message in problems:
            self.stdout.write(f"{level}: {source}: {message}")
        errors = sum(1 for level, _source, _message in problems if level == "error")
        self.stdout.write(f"{len(all_pages())} page(s), {errors} error(s).")
        if errors:
            raise CommandError(f"{errors} guide error(s).")
