# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Evennia Script for the RP activity tracker.

This module is imported lazily — only when ``create_script()`` resolves the
dotted path ``evennia_rptracker.scripts.RPIdleCheckScript`` (from
``tracker.ensure_idle_check_running()``, called at server start). By that
point Evennia is fully initialized, so ``DefaultScript`` is guaranteed
available. Keeping this out of ``tracker.py`` (which is imported eagerly
during Django's app-loading phase) avoids binding ``RPIdleCheckScript`` to
``None`` when ``DefaultScript`` isn't ready yet.
"""

from evennia import DefaultScript


class RPIdleCheckScript(DefaultScript):
    """Evennia Script that periodically closes idle RP sessions."""

    def at_script_creation(self):
        from django.conf import settings

        self.key = "rp_idle_check"
        self.desc = "Closes idle RPTracker sessions."
        self.interval = getattr(settings, "RPTRACKER_IDLE_CHECK_INTERVAL", 300)
        self.persistent = True
        self.repeats = 0

    def at_repeat(self):
        from evennia_rptracker.tracker import _check_idle_sessions

        _check_idle_sessions()
