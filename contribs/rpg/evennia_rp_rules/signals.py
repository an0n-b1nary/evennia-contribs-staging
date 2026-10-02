# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Signals for evennia_rp_rules.

check_resolved — fired by `resolve_check()` after every resolved check (never
                 for estimates). sender: the `Check` class.
                 kwargs: check (Check), result (CheckResult)

Receivers that only care about one system filter on `check.kind`. A receiver
that raises propagates to whoever called `resolve_check()`, so a game that
wraps the check and its record in a transaction rolls both back together.
"""

from django.dispatch import Signal

check_resolved = Signal()

__all__ = ["check_resolved"]
