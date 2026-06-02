# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for evennia_lore.

lore_entry_created   — fires when a LoreEntry is created via LoreEntry.create_entry().
lore_entry_published — fires when a LoreEntry transitions to PUBLISHED status.
lore_entry_edited    — fires when a LoreEntry body is edited (after a LoreVersion snapshot).
lore_acquired        — fires when a LoreAcquisition row is created for a character.
                       Connect notification/XP systems to this signal in your game.
"""

from django.dispatch import Signal

lore_entry_created = Signal()
lore_entry_published = Signal()
lore_entry_edited = Signal()
lore_acquired = Signal()
