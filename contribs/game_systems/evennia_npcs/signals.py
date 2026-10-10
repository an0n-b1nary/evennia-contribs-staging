# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional consumers can observe NPC activity without reverse dependencies."""

from django.dispatch import Signal

npc_pose_recorded = Signal()  # npc, actor, text, pose_type
