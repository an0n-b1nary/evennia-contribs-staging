# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional SOCIAL_PROFILE_PROVIDERS callback; reveal policy follows the viewer."""

from . import conf
from .gathering import lean_description


def gathering_field(viewer, target):
    return {"Gathering": lean_description(target)} if conf.visible(viewer) else {}
