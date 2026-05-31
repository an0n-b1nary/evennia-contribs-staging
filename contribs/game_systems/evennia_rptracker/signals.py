# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for the RP activity tracker.

These signals allow domain apps to react to tracker events without the
tracker importing from them. See README for the integration recipe.

Signals:
- rp_session_started: fired when an RPSession transitions from pending
  to active (activation threshold met). Kwargs: session (RPSession).
- rp_session_ended: fired when an RPSession completes (idle timeout,
  disconnect, or manual end). Kwargs: session (RPSession).
- rp_activity_recorded: fired on each qualifying pose during an active
  session. Kwargs: character (ObjectDB), session_id (int), room (ObjectDB).
"""

from django.dispatch import Signal

rp_session_started = Signal()
rp_session_ended = Signal()
rp_activity_recorded = Signal()
