# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signals fired by evennia_scenes for cross-system listeners.

Other apps connect to these signals; evennia_scenes never imports from them.

Signal kwargs:
    scene_opened:      scene (Scene), creator (ObjectDB)
    scene_started:     scene (Scene)
    scene_closed:      scene (Scene), closer (ObjectDB or None)
    log_entry_created: entry (LogEntry), scene (Scene)
"""

from django.dispatch import Signal

scene_opened = Signal()
scene_started = Signal()
scene_closed = Signal()
log_entry_created = Signal()
