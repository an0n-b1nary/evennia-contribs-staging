# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The storyteller is a player; editing and voiding require ownership or staff."""

from evennia_rp_contest import conf


def is_staff(caller):
    return caller.locks.check_lockstring(caller, conf.get("RP_CONTEST_STAFF_LOCK"))


def can_set(caller):
    return caller.locks.check_lockstring(caller, conf.get("RP_CONTEST_CAN_SET_CHALLENGE"))


def can_manage(caller, challenge):
    return challenge.set_by_id == caller.pk or is_staff(caller)
