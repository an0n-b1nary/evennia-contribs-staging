# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Contest settings; no stat, tag or grade names are baked in."""

from datetime import timedelta

from django.conf import settings

DEFAULTS = {
    "RP_CONTEST_STAFF_LOCK": "cmd:perm(Builder)",
    "RP_CONTEST_CAN_SET_CHALLENGE": "cmd:all()",
    "RP_CONTEST_DEFAULT_DIFFICULTY": None,
    "RP_CONTEST_DIFFICULTIES": {},
    "RP_CONTEST_TAG_KIND": ["domain", "element"],
    "RP_CONTEST_NARRATION": "evennia_rp_contest.narration.announce_test",
    "RP_CONTEST_SHOW_RATINGS_TO_ROOM": False,
    "RP_CONTEST_COMMENT_MAX": 500,
    "RP_CONTEST_CHALLENGE_IDLE_TTL": 3 * 60 * 60,
    "RP_CONTEST_SCENE_ID_RESOLVER": None,
    "RP_CONTEST_SCENES_APP_LABEL": "evennia_scenes",
    "RP_CONTEST_RPTRACKER_APP_LABEL": "evennia_rptracker",
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])


def idle_ttl():
    value = get("RP_CONTEST_CHALLENGE_IDLE_TTL")
    return value if value is None or isinstance(value, timedelta) else timedelta(seconds=value)
