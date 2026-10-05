# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public contest API, with atomic numbering, repeat checks and audit writes."""

from django.apps import apps
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from evennia_links import resolve_dotted
from evennia_rp_contest import conf, narration, permissions, signals
from evennia_rp_contest.difficulty import resolve_difficulty
from evennia_rp_contest.models import Challenge, CheckRecord, RoomSequence
from evennia_rp_contest.parsing import ContestError, limited
from evennia_rp_rules.checks import Check, CheckError, resolve_check


def room_for(caller):
    room = caller.location
    if room is None:
        raise ContestError("You need to be in a room to test or set a challenge.")
    return room


def scene_id_for(caller):
    """A game resolver(caller), the gated scenes partner, or None."""
    path = conf.get("RP_CONTEST_SCENE_ID_RESOLVER")
    if path:
        return resolve_dotted(path)(caller)
    label = conf.get("RP_CONTEST_SCENES_APP_LABEL")
    if apps.is_installed(label) or any(cfg.label == label for cfg in apps.get_app_configs()):
        from evennia_rp_contest.integrations.scenes import scene_id_for as partner_resolver

        return partner_resolver(caller)
    return None


def find_challenge(caller, number, *, open_only=False):
    from evennia_rp_contest.expiry import sweep_idle

    room = room_for(caller)
    sweep_idle(room=room)
    challenge = Challenge.objects.filter(room=room, number=number).first()
    if challenge is None:
        raise ContestError(f"No challenge #{number} in this room.")
    if open_only and challenge.status != Challenge.Status.OPEN:
        raise ContestError(f"Challenge #{number} is closed.")
    return challenge


def require_manager(caller, challenge):
    if not permissions.can_manage(caller, challenge):
        raise ContestError("Only the setter or staff can manage this challenge.")


def _difficulty(req):
    try:
        return resolve_difficulty(req.difficulty, stat=req.stat).display()
    except (ValueError, KeyError) as exc:
        raise ContestError(f"Invalid difficulty: {exc}") from exc


def open_challenge(caller, req):
    if not permissions.can_set(caller):
        raise ContestError("You may not set challenges.")
    room = room_for(caller)
    difficulty = _difficulty(req)
    scene_id = scene_id_for(caller)
    # The UPDATE is the first statement in the transaction, acquiring a write
    # lock on SQLite too (select_for_update alone would not).
    sequence, _ = RoomSequence.objects.get_or_create(room=room)
    with transaction.atomic():
        RoomSequence.objects.filter(pk=sequence.pk).update(number=F("number") + 1)
        sequence.refresh_from_db()
        challenge = Challenge.objects.create(
            room=room,
            room_name=room.key,
            number=sequence.number,
            set_by=caller,
            set_by_name=caller.key,
            difficulty=difficulty,
            description=limited(req.description),
            stat_key=req.stat,
            tag=req.tag,
            once=req.once,
            scene_id=scene_id,
        )
    signals.challenge_opened.send(sender=Challenge, challenge=challenge, actor=caller)
    narration.announce_challenge(challenge, verb="sets", actor=caller)
    return challenge


def edit_challenge(caller, challenge, req):
    require_manager(caller, challenge)
    difficulty = _difficulty(req)
    with transaction.atomic():
        changed = Challenge.objects.filter(pk=challenge.pk, status=Challenge.Status.OPEN).update(
            difficulty=difficulty,
            description=limited(req.description),
            stat_key=req.stat,
            tag=req.tag,
            edited_at=timezone.now(),
            edited_by=caller,
        )
        if not changed:
            raise ContestError("That challenge is closed.")
        challenge.refresh_from_db()
    signals.challenge_edited.send(sender=Challenge, challenge=challenge, actor=caller)
    narration.announce_challenge(challenge, verb="edits", actor=caller)
    return challenge


def set_once(caller, challenge):
    require_manager(caller, challenge)
    changed = Challenge.objects.filter(pk=challenge.pk, status=Challenge.Status.OPEN).update(
        once=True
    )
    if not changed:
        raise ContestError("That challenge is closed.")
    challenge.refresh_from_db()
    signals.challenge_edited.send(sender=Challenge, challenge=challenge, actor=caller)
    narration.announce_challenge(challenge, verb="marks once", actor=caller)
    return challenge


def close_challenge(challenge, *, caller=None, reason="manual", idle_before=None):
    if caller is not None:
        require_manager(caller, challenge)
    queryset = Challenge.all_objects.filter(pk=challenge.pk, status=Challenge.Status.OPEN)
    if idle_before is not None:
        queryset = queryset.filter(last_activity__lte=idle_before)
    changed = queryset.update(
        status=Challenge.Status.CLOSED,
        closed_reason=reason,
    )
    if changed:
        challenge.refresh_from_db()
        signals.challenge_closed.send(sender=Challenge, challenge=challenge, actor=caller)
        narration.announce_challenge(challenge, verb="closes", actor=caller)
    return bool(changed)


def void_attempt(caller, challenge, attempt, *, reason=""):
    """`attempt` is the record id shown by /history, unique across actors."""
    require_manager(caller, challenge)
    reason = limited(reason)
    record = CheckRecord.objects.filter(pk=attempt, challenge=challenge).first()
    if record is None:
        raise ContestError("No such attempt on this challenge. Use the id in +test/history.")
    changed = CheckRecord.objects.filter(pk=record.pk, voided_at__isnull=True).update(
        voided_at=timezone.now(),
        voided_by=caller,
        void_reason=reason,
    )
    if not changed:
        raise ContestError("That attempt is already void.")
    record.refresh_from_db()
    signals.check_voided.send(sender=CheckRecord, record=record, actor=caller)
    narration.emit(
        challenge.room,
        "{actor} voids attempt {attempt} on #{number}.{reason}",
        {
            "actor": caller.key,
            "attempt": record.pk,
            "number": challenge.number,
            "reason": f" {reason}" if reason else "",
        },
        actor=caller,
    )
    return record


def bind_challenge(caller, req):
    from evennia_rp_contest.expiry import sweep_idle

    room = room_for(caller)
    sweep_idle(room=room)
    if req.challenge_number is not None:
        return find_challenge(caller, req.challenge_number, open_only=True)
    matches = [
        c
        for c in Challenge.objects.filter(room=room, status=Challenge.Status.OPEN)
        if (not c.stat_key or c.stat_key == req.stat) and (not c.tag or c.tag == req.tag)
    ]
    if len(matches) == 1:
        return matches[0]
    # Ambiguous or unmatched automatic binding uses the ad-hoc difficulty.
    return None


def perform_test(caller, req, *, roller=None):
    room = room_for(caller)
    challenge = bind_challenge(caller, req)
    scene_id = scene_id_for(caller)
    with transaction.atomic():
        if challenge:
            # Serialize attempts and edits with a real write, including SQLite.
            Challenge.objects.filter(pk=challenge.pk).update(last_activity=F("last_activity"))
            challenge.refresh_from_db()
            if challenge.status != Challenge.Status.OPEN or challenge.is_archived:
                raise ContestError("That challenge is closed.")
            attempts = CheckRecord.objects.filter(challenge=challenge, character=caller)
            if challenge.once and attempts.filter(voided_at__isnull=True).exists():
                raise ContestError("This challenge allows only one attempt per character.")
            attempt_no = (attempts.aggregate(n=Max("attempt_no"))["n"] or 0) + 1
        else:
            attempt_no = 1
        try:
            difficulty = resolve_difficulty(
                challenge.difficulty if challenge else None, stat=req.stat
            )
            result = resolve_check(
                Check(
                    "test",
                    caller,
                    req.stat,
                    tags=[req.tag] if req.tag else [],
                    difficulty=difficulty,
                    context={
                        "room": room.pk,
                        "scene_id": scene_id,
                        "challenge": challenge.pk if challenge else None,
                    },
                ),
                roller=roller,
                send_signal=False,
            )
        except (CheckError, ValueError, KeyError) as exc:
            raise ContestError(str(exc)) from exc
        alternative = bool(
            challenge
            and (
                (challenge.stat_key and challenge.stat_key != req.stat)
                or (challenge.tag and challenge.tag != req.tag)
            )
        )
        record = CheckRecord.objects.create(
            character=caller,
            actor_name=caller.key,
            room=room,
            room_name=room.key,
            scene_id=scene_id,
            challenge=challenge,
            attempt_no=attempt_no,
            stat=req.stat,
            tag=req.tag,
            rating_display=result.actor_rating.display(),
            difficulty=difficulty.display(),
            outcome_key=result.outcome.key,
            outcome_degree=result.outcome.degree,
            is_success=result.is_success,
            comment=limited(req.comment),
            alternative=alternative,
            detail=result.as_dict(),
        )
        if challenge:
            Challenge.objects.filter(pk=challenge.pk).update(last_activity=timezone.now())
        # Signals are transactional so real scene logging rolls back with the record.
        from evennia_rp_rules.signals import check_resolved

        check_resolved.send(sender=Check, check=result.check, result=result)
        signals.check_recorded.send(sender=CheckRecord, record=record, result=result)
    resolve_dotted(conf.get("RP_CONTEST_NARRATION"))(record, result=result)
    caller.msg(
        (
            f"Your test: {record.rating_display} vs {record.difficulty}: {result.outcome.label}.",
            narration.MESSAGE_TYPE.copy(),
        )
    )
    return record
