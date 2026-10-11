# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Post-commit membership seam for companion/ambient automation consumers."""

from django.dispatch import Signal

membership_changed = Signal()  # character_id, fight_id, status, actor_id
