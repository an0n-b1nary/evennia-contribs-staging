# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for evennia_regions.

region_created — fires when a Region is created via Region.create_region().
                 Ships with zero receivers; a game or partner contrib may
                 connect its own listeners (e.g. lore trickle, notifications).
"""

from django.dispatch import Signal

region_created = Signal()
