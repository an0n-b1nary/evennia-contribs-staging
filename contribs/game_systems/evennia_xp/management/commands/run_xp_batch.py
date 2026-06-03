# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Management command: run_xp_batch

Manually trigger the weekly XP batch outside the scheduled Script. Useful for
backfills, debugging, and smoke tests.

Usage:
    evennia run_xp_batch
    evennia run_xp_batch --week=2026-W18
    evennia run_xp_batch --dry-run
    evennia run_xp_batch --week=2026-W18 --dry-run
    evennia run_xp_batch --source=rp_session,lore_authored

Note: Evennia's management commands are invoked via the ``evennia`` CLI, which
wraps Django's manage.py.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the weekly XP batch. Defaults to the most recently completed ISO week."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week",
            metavar="YYYY-Www",
            default=None,
            help=("ISO week to process, e.g. 2026-W18. " "Defaults to the last completed week."),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Compute awards without writing any XPLog rows or calling hooks.",
        )
        parser.add_argument(
            "--source",
            metavar="SOURCES",
            default=None,
            help=(
                "Comma-separated list of source keys to run, e.g. "
                "rp_session,lore_authored.  Runs all collectors if omitted."
            ),
        )

    def handle(self, *args, **options):
        week = options["week"]
        dry_run = options["dry_run"]
        source_arg = options["source"]

        # Validate --week format.
        if week:
            import re

            if not re.fullmatch(r"\d{4}-W\d{2}", week):
                raise CommandError(
                    f"--week must be in YYYY-Www format, e.g. 2026-W18. Got: {week!r}"
                )

        # Parse --source (keys are game-defined via XP_COLLECTORS).
        sources = None
        if source_arg:
            sources = [s.strip() for s in source_arg.split(",") if s.strip()]

        from evennia_xp.batch import run_weekly_batch

        mode = "DRY RUN" if dry_run else "LIVE"
        self.stdout.write(
            self.style.NOTICE(
                f"XP batch [{mode}]: week={week or 'auto'} sources={sources or 'all'}"
            )
        )

        summary = run_weekly_batch(week=week, dry_run=dry_run, sources=sources)

        self.stdout.write(self.style.SUCCESS(f"\nWeek: {summary.week}"))
        self.stdout.write(f"Total awards: {summary.total_awards}")
        self.stdout.write(f"Total XP:     {summary.total_xp}")

        if summary.by_source:
            self.stdout.write("\nBy source:")
            for src, stats in sorted(summary.by_source.items()):
                self.stdout.write(f"  {src:25s} {stats['count']:4d} awards  {stats['total']} XP")

        if summary.errors:
            self.stdout.write(self.style.ERROR(f"\n{len(summary.errors)} error(s):"))
            for err in summary.errors:
                self.stdout.write(self.style.ERROR(f"  {err}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo errors."))

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No rows were written."))
