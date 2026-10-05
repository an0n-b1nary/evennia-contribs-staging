# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public hooks: record=CheckRecord, challenge=Challenge, actor=ObjectDB.

check_recorded also includes result=CheckResult. Void/edit/close hooks include
actor (None for expiry); opening includes actor. No XP or rewards are granted.
"""

from django.dispatch import Signal

check_recorded = Signal()
check_voided = Signal()
challenge_opened = Signal()
challenge_edited = Signal()
challenge_closed = Signal()
