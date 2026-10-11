# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Absence maintenance; never chooses a reaction or outgoing action.

Presence follows the player's connection: a participant is idle once their
player (the NPC's controller, for an NPC) has sent no command at all for
RP_COMBAT_IDLE_SECONDS, or has been disconnected that long. Waiting quietly
for others' poses is not idleness while the player is connected and chatting.
"""

import time
import uuid

from django.db import transaction
from evennia.objects.models import ObjectDB
from evennia.utils import logger

from . import conf, engine, services


def maintain_all(*, now=None):
    from .models import Fight

    for pk in Fight.objects.filter(status=Fight.OPEN).values_list("pk", flat=True):
        try:
            maintain(pk, now=now)
        except Exception:  # One fight's fault must never stall every other fight.
            logger.log_trace(f"rp_combat: maintenance failed for fight #{pk}")


def last_seen(player):
    """When the player last sent any command, or None while disconnected."""
    idle = player.idle_time if player is not None else None
    return None if idle is None else time.time() - idle


def maintain(fight, *, now=None):
    from .models import Fight

    now = time.time() if now is None else now
    pk = getattr(fight, "pk", fight)
    with transaction.atomic():
        fight = Fight.objects.select_for_update().filter(pk=pk, status=Fight.OPEN).first()
        if fight is None:
            return
        try:
            services.validate_state(fight.state)
        except engine.CombatError:
            if not fight.unsupported_notice:
                fight.unsupported_notice = True
                fight.save(update_fields=["unsupported_notice"])
                room = fight.room
                transaction.on_commit(
                    lambda: services.emit(
                        room,
                        None,
                        "Unsupported combat state version; fight suspended for staff restoration or migration.",
                    )
                )
            return
        state = services.clone(fight.state)
        if state["ended"]:
            return
        before = services.clone(state)
        notices = []
        close = None
        if fight.room is None:
            # The room was deleted. Shelve the fight so nobody loses their place.
            services.shelve_state(state)
            notices.append("The fight's room no longer exists; the fight was shelved.")
            close = Fight.SHELVED
        presence = dict(fight.presence)
        idle_limit = conf.get("RP_COMBAT_IDLE_SECONDS")
        for row in state["participants"].values() if close is None else ():
            if row["status"] != "active":
                continue
            obj = ObjectDB.objects.filter(pk=row["id"]).first()
            absent = obj is None or obj.location != fight.room
            player = obj
            if obj and row["npc"]:
                record = services.npc_record(obj)
                player = services.owner(obj)
                if record is None or player is None:
                    absent = True
                else:
                    from evennia_npcs.services import can_play

                    absent = absent or not can_play(player, record.blueprint)
            seen = last_seen(player)
            if seen is not None:
                presence[row["id"]] = max(presence.get(row["id"], 0), seen)
            seen = max(presence.get(row["id"], 0), row.get("last_activity", now))
            absent = absent or (idle_limit > 0 and now - seen >= idle_limit)
            if not absent:
                if row.pop("absent", None):
                    notices.append(f"{row['name']} is present again and may continue.")
                continue
            services.release_pending(state, row)
            if not row["incoming"] and not row["outgoing"]:
                was_paused = state["paused"]
                engine.fade(state, row["id"])
                row.pop("absent", None)
                notices.append(
                    f"{row['name']} Faded after absence, idle time or NPC control loss; "
                    "their place, build and contributions are retained and +combat/join restores them."
                )
                if state["paused"] and not was_paused:
                    notices.append("Nobody is active, so the fight is paused.")
            else:
                if not row.get("absent"):
                    notices.append(
                        f"{row['name']} is absent with an accepted reaction; it remains committed while peers finish or staff recover the exchange."
                    )
                row["absent"] = True
        if presence != fight.presence:
            fight.presence = presence
            fight.save(update_fields=["presence"])
        if state == before:
            return
        if close:
            fight.status = close
        summary = " ".join(notices) or "Absence cleanup canceled unaccepted packets."
        services.commit(
            fight,
            before,
            state,
            actor=None,
            label=summary,
            operation_id=str(uuid.uuid4()),
            result=summary,
            summary=summary,
            sequence=services.next_sequence(fight),
        )


def note_pose(sender, character=None, npc=None, pose_type="pose", **kwargs):
    from .models import Fight

    character = character or npc
    if character is None or character.location is None or pose_type == "ooc":
        return
    fight = Fight.objects.filter(room=character.location, status=Fight.OPEN).first()
    if fight is None or str(character.pk) not in fight.state.get("participants", {}):
        return

    def mutate(state):
        row = state["participants"].get(str(character.pk))
        if row and not state["ended"]:
            row["last_activity"], row["pose"] = time.time(), False

    services.quietly(fight, mutate)


def object_deleted(sender, instance, **kwargs):
    if not isinstance(instance, ObjectDB):
        return
    from .models import Fight

    key = str(instance.pk)
    for fight in Fight.objects.filter(status=Fight.OPEN).only("pk", "state"):
        if key in fight.state.get("participants", {}):
            transaction.on_commit(lambda pk=fight.pk: maintain(pk))
