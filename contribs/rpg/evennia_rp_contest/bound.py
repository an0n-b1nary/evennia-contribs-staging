# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Snapshot and resolve host-bound attempts without room-challenge matching.

The host owns authorization, its transaction/lock, attempt uniqueness and
rollback. Private attempt details stay in CheckRecord; public results are
small binding-checked values. There is no combat dependency here.
"""

from fractions import Fraction as F

from django.db import connection

from evennia_links.guests import is_guest
from evennia_rp_rules.checks import Check, estimate_check
from evennia_rp_rules.pipeline import default_roller
from evennia_rp_rules.resolvers import Contest
from evennia_rp_rules.ruleset import get_ruleset
from evennia_rp_rules.subjects import DictStatSource, get_subject
from evennia_rp_rules.vocabulary import get_vocabulary

from .difficulty import resolve_difficulty
from .models import CheckRecord
from .parsing import ContestError, approach


def difficulty_for(stat, text=None):
    if text is not None:
        return resolve_difficulty(text, stat=stat)
    scale = get_ruleset().stats[stat].scale
    return scale.parse(scale.rungs[len(scale.rungs) // 2].key)


def snapshot(subject, *, stats=None):
    """Freeze base ratings and folded approach modifiers at build lock time.

    Modifiers are evaluated as a host-bound check at each stat's middle
    difficulty. Later challenges choose difficulty, never reread the sheet
    or rerun live modifier providers. Rating/dice data is private host state.
    """
    if is_guest(subject):
        return None
    ruleset = get_ruleset()
    source = DictStatSource(stats) if stats is not None else get_subject(subject)
    if source is None:
        return None
    tags = [None, *(tag.key for tag in get_vocabulary().tags())]
    values = {}
    for stat in ruleset.stats:
        if source.get_rating(stat) is None:
            continue
        difficulty = difficulty_for(stat)
        for tag in tags:
            check = Check(
                "bound_contest",
                subject if stats is None else source,
                stat,
                tags=[tag] if tag else [],
                difficulty=difficulty,
            )
            estimate = estimate_check(check, viewer="staff")
            key = stat + (f"/{tag}" if tag else "")
            values[key] = {
                "rating": estimate.effective["actor"].display(),
                "bonus": str(estimate.bonuses["actor"]),
            }
    return {"schema": 1, "ruleset": ruleset.digest, "approaches": values}


def approaches(snapshot, names, difficulty=None):
    if not snapshot or snapshot.get("ruleset") != get_ruleset().digest:
        raise ContestError("No compatible frozen Contest source; explicitly relock the build.")
    result = {}
    for name in names:
        stat, tag = approach(name)
        key = stat + (f"/{tag}" if tag else "")
        if key not in snapshot["approaches"]:
            raise ContestError("That approach is not available in the frozen Contest source.")
        result[key] = difficulty_for(stat, difficulty).display()
    if not result:
        raise ContestError("Declare at least one allowed Contest approach.")
    return result


def perform(subject, snapshot, allowed, name, *, binding, roller=None):
    """Create one audit attempt inside the host's locked transaction.

    No callbacks/signals or room matching can apply awards outside that
    transaction. The host journals the returned binding and enforces once.
    """
    if not connection.in_atomic_block:
        raise ContestError("A bound Contest attempt needs its host transaction.")
    if is_guest(subject):
        raise ContestError("Guests cannot commit shared bound Contest attempts.")
    normalized = approaches(snapshot, [name], None)
    key = next(iter(normalized))
    if key not in allowed:
        raise ContestError("Choose one of this Check's declared approaches.")
    stat, _, tag = key.partition("/")
    ruleset = get_ruleset()
    scale = ruleset.stats[stat].scale
    frozen = snapshot["approaches"][key]
    result = ruleset.resolver.resolve(
        Contest(
            scale.parse(frozen["rating"]), scale.parse(allowed[key]), actor_bonus=F(frozen["bonus"])
        ),
        roller or default_roller(),
    )
    record = CheckRecord.objects.create(
        character=subject,
        actor_name=subject.key,
        room=subject.location,
        room_name=subject.location.key,
        stat=stat,
        tag=tag or None,
        rating_display=frozen["rating"],
        difficulty=allowed[key],
        outcome_key=result.outcome.key,
        outcome_degree=result.outcome.degree,
        is_success=result.is_success,
        detail={
            "binding": binding,
            "ruleset": ruleset.digest,
            "outcome": {"key": result.outcome.key, "label": result.outcome.label},
            "resolution": result.as_dict(),
        },
    )
    return {"record": record.pk, "success": record.is_success, "approach": key}


def validate(result, *, subject_id, binding):
    records = CheckRecord.objects.all()
    if connection.in_atomic_block:
        records = records.select_for_update()
    record = records.filter(pk=result["record"]).first()
    if (
        record is None
        or record.voided
        or record.character_id != int(subject_id)
        or record.detail.get("binding") != binding
        or record.is_success is not result["success"]
    ):
        raise ContestError("That bound attempt was voided or changed; reconcile before resolution.")
