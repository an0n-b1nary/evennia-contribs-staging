# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signal fired whenever a pose, emit, say, or semipose is recorded.

Lets domain apps (scene loggers, RP trackers, XP collectors) react to posing
activity without this contrib importing from them. See README "Integration
recipe" for the recommended single-listener wiring pattern — connect exactly
one receiver in your game and have it call your downstream consumers in the
order you choose, rather than relying on multi-receiver signal ordering
(which Django does not guarantee).

Signal:
- pose_recorded: fired by PosingCharacterMixin.record_pose() every time a
  pose, emit, say, or semipose is recorded. Kwargs:
    character (ObjectDB)  — the posing character
    pose_text (str)       — the full text of the pose
    pose_type (str)       — one of "pose", "emit", "say" (semipose fires
                             with pose_type="pose" — see CmdSemipose)
    location (ObjectDB or None) — the character's room at the time of posing
"""

from django.dispatch import Signal

pose_recorded = Signal()
