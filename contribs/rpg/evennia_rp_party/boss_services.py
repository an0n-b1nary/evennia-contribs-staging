# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authorized manual Check operations in combat's journal transaction."""

import hashlib
import json
import random

from evennia.objects.models import ObjectDB
from evennia_rp_combat import engine
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import CombatError

from evennia_links.guests import is_guest

from . import boss, rules, services, subjects


def contest_provider():
    provider = subjects.contest_provider()
    if provider is None:
        raise CombatError(
            "Compatible Contest provider unavailable; install contest 0.1.4+ for this type. Other Check types remain available."
        )
    return provider


def party_keys(state, names):
    keys = []
    for name in names:
        candidates = [
            key
            for key, row in rules.data(state)["parties"].items()
            if not row["dissolved"] and (name == key or name.casefold() == row["name"].casefold())
        ]
        if len(candidates) != 1:
            raise CombatError("Name an existing Party identity or exact Party name.")
        keys.append(candidates[0])
    return keys


def interact(actor, state, ids):
    if is_guest(actor):
        raise CombatError("Guests cannot take part in shared Boss Checks.")
    for ident in ids:
        target = ObjectDB.objects.filter(pk=ident).first()
        if is_guest(target):
            raise CombatError("Guests cannot take part in shared Boss Checks.")
        if target is None or target.location != actor.location:
            raise CombatError("A Check participant has left the room; suspend or cancel the Check.")
        combat.interaction(actor, target)


def source(state, ident):
    return engine.participant(state, ident).get("partner_subjects", {}).get("party")


def _execute(actor, subject, operation, request, callback, *, cleanup=False, operation_id=None):
    services.require(actor, progress=not cleanup)
    if not cleanup and (is_guest(actor) or is_guest(subject)):
        raise CombatError("Guests cannot take part in shared Boss Checks.")
    combat.authorize(actor, subject, cleanup=cleanup)
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
    return combat.execute(
        actor,
        f"{combat.identity(subject)} Boss Check {operation} {digest}",
        callback,
        progressing=not cleanup,
        subject=subject,
        operation_id=operation_id,
    )


def issue(
    actor,
    parties,
    kind,
    *,
    subject=None,
    difficulty="balanced",
    options=None,
    approaches=(),
    roll_difficulty=None,
    operation_id=None,
):
    subject = subject or actor
    options = options or {}
    request = [parties, kind, difficulty, options, list(approaches), roll_difficulty]

    def apply(state):
        keys = party_keys(state, parties)
        targets = [ident for key in keys for ident in rules.counted(state, key)]
        interact(subject, state, targets)
        allowed = None
        if kind == "contest":
            provider = contest_provider()
            allowed = {
                ident: provider.approaches(source(state, ident), approaches, roll_difficulty)
                for ident in targets
            }
        elif approaches or roll_difficulty is not None:
            raise CombatError("Only Contest Checks declare stat approaches and roll difficulty.")
        ids = boss.issue(
            state,
            subject.pk,
            keys,
            kind,
            difficulty=difficulty,
            options=options,
            contest=allowed,
            contest_difficulty=roll_difficulty,
        )
        for ident in ids:
            check = boss.get(state, ident)
            combat.notice(
                state,
                f"{check['kind']} Check {ident} issued to {rules.party(state, check['party'])['name']} ({difficulty}); {len(check['cohort'])} targets; requirement {boss.required(check, len(check['cohort']))}; failure {check['profile']['failure']} per target.",
            )
            if kind == "special":
                combat.notice(state, f"Requirement: {options['requirement']}")
                combat.notice(state, f"Hint: {options['hint']}; interpret responses generously.")
            if kind == "contest":
                combat.notice(
                    state,
                    f"Contest approaches: {', '.join(approaches)}; roll difficulty {roll_difficulty or 'middle'}; one free bound response each.",
                )
            for warning in boss.warnings(state, check):
                combat.notice(state, warning)
        combat.notice(
            state,
            "Targets may +bosscheck/withdraw their own participation or /cancel their Party's Check before commitment. No automatic deadline.",
        )
        return ids

    return _execute(actor, subject, "issue", request, apply, operation_id=operation_id)


def cancel(actor, ident, *, subject=None, individual=False, reason="", operation_id=None):
    subject = subject or actor
    reason = combat.plain(reason, 240)

    def apply(state):
        boss.cancel(state, ident, subject.pk, individual=individual, reason=reason)
        combat.notice(
            state,
            f"{combat.identity(subject)} {'withdrew individual participation in' if individual else 'canceled the Party instance of'} Check {ident}. {reason}",
        )
        return "withdrawn" if individual else "canceled"

    return _execute(
        actor,
        subject,
        "withdraw" if individual else "cancel",
        [ident, reason],
        apply,
        cleanup=True,
        operation_id=operation_id,
    )


def validate_attempts(state, check):
    if check["kind"] != "contest":
        return
    provider = contest_provider()
    for ident in boss.eligible(state, check):
        attempt = check["attempts"].get(ident)
        if attempt:
            provider.validate(attempt, subject_id=ident, binding=attempt["binding"])


def preview(actor, ident, *, subject=None, verdict=None):
    subject = subject or actor
    services.require(actor)
    combat.authorize(actor, subject, cleanup=True)
    state = combat.state_for(actor)
    check = boss.get(state, ident)
    if str(subject.pk) != check["boss"]:
        raise CombatError("The boss's authorized controller previews and resolves its Check.")
    validate_attempts(state, check)
    return boss.preview(state, ident, verdict=verdict)


def resolve(
    actor,
    ident,
    token,
    *,
    subject=None,
    verdict=None,
    acknowledgment="",
    rng=None,
    operation_id=None,
):
    subject = subject or actor
    acknowledgment = combat.plain(acknowledgment, 240)

    def apply(state):
        check = boss.get(state, ident)
        if str(subject.pk) != check["boss"]:
            raise CombatError("Only the boss's authorized controller resolves this Check.")
        ids = boss.boundary(state, check)
        interact(subject, state, ids)
        validate_attempts(state, check)
        # Verify before consuming any draws. No draw is exposed by preview.
        view = boss.preview(state, ident, verdict=verdict)
        if token != view["token"]:
            raise CombatError("That Check preview is stale; preview the current state again.")
        if view["warnings"] and not acknowledgment.strip():
            raise CombatError(
                "Acknowledge the Check warnings with a public reason before resolving."
            )
        draws = {
            i: (rng or random.SystemRandom()).randint(1, 100)
            for i in ids
            if check["kind"] == "tank" and rules.position(state, i) == "front"
        }
        result = boss.resolve(
            state, ident, token, verdict=verdict, acknowledgment=acknowledgment, draws=draws
        )
        combat.notice(
            state,
            f"Check {ident}: {'passed' if result['passed'] else 'failed'}; eligible {len(result['eligible'])}, requirement {result['threshold']}, Backlash {result['backlash']}, Front collapse {result['collapse']}. Acknowledgment: {acknowledgment or 'none needed'}.",
        )
        for member, value in result["damage"].items():
            combat.notice(
                state,
                f"Check {ident} damage {member}: {value['damage'] if isinstance(value, dict) else value}.",
            )
        return result

    return _execute(
        actor,
        subject,
        "resolve",
        [ident, token, verdict, acknowledgment],
        apply,
        operation_id=operation_id,
    )


def roll(actor, ident, approach, *, subject=None, roller=None, operation_id=None):
    subject = subject or actor

    def apply(state):
        provider = contest_provider()
        check = boss.get(state, ident)
        member = str(subject.pk)
        if (
            check["status"] != "pending"
            or check["kind"] != "contest"
            or member not in boss.eligible(state, check)
        ):
            raise CombatError("You have no eligible pending Contest Check response.")
        engine.progress(state)
        engine.active(state, check["boss"])
        if member in check["attempts"]:
            raise CombatError("One bound Contest attempt per participant; no rerolls.")
        interact(subject, state, [check["boss"]])
        binding = {
            "kind": "party_boss_check",
            "fight": combat.open_fight(actor.location).pk,
            "epoch": state["epoch"],
            "check": ident,
            "participant": member,
        }
        result = provider.perform(
            subject,
            check["contest_sources"].get(member),
            check["allowed"][member],
            approach,
            binding=binding,
            roller=roller,
        )
        result["binding"] = binding
        check["attempts"][member] = result
        combat.notice(
            state,
            f"{combat.identity(subject)} Contest Check {ident} response: {'pass' if result['success'] else 'fail'} via {result['approach']}. Ratings and dice remain private.",
        )
        return result

    return _execute(actor, subject, "roll", [ident, approach], apply, operation_id=operation_id)


def allow(actor, ident, member, approach, *, subject=None, operation_id=None):
    subject = subject or actor

    def apply(state):
        check = boss.get(state, ident)
        key = str(member.pk)
        if (
            str(subject.pk) != check["boss"]
            or check["status"] != "pending"
            or check["kind"] != "contest"
            or key not in boss.eligible(state, check)
        ):
            raise CombatError("The boss controller may approve an eligible Contest approach.")
        if key in check["attempts"]:
            raise CombatError("Approve alternatives before rolling, never after seeing a result.")
        interact(subject, state, [key])
        # Keep the Check's already-authored roll difficulty, not a new easier one.
        difficulty = check["contest_difficulty"]
        value = contest_provider().approaches(
            check["contest_sources"].get(key), [approach], difficulty
        )
        check["allowed"][key].update(value)
        combat.notice(
            state,
            f"Contest Check {ident}: {combat.identity(member)} may use {next(iter(value))}, approved before rolling.",
        )
        return next(iter(value))

    return _execute(
        actor, subject, "allow", [ident, str(member.pk), approach], apply, operation_id=operation_id
    )
