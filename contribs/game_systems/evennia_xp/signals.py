# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for evennia_xp.

xp_awarded        — fired when a new XPLog row is written. Kwargs:
                    character_id (int), xplog (XPLog instance), source_type (str).
xp_batch_completed — fired at the end of run_weekly_batch. Kwargs:
                    summary (BatchSummary), week (str ISO week).
"""

from django.dispatch import Signal

xp_awarded = Signal()
xp_batch_completed = Signal()
