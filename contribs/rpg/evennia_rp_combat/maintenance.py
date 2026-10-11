# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Absence maintenance; never chooses a reaction or outgoing action."""

import time
import uuid
from datetime import UTC, datetime

from django.db import transaction
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB

from . import conf, engine, services


def maintain(script, *, now=None):
    now = time.time() if now is None else now
    with transaction.atomic():
        if (
            not ScriptDB.objects.select_for_update().filter(pk=script.pk).exists()
            or script.obj is None
        ):
            return
        script.attributes.reset_cache()
        state = services.clone(script.db.state)
        try:
            services.validate_state(state)
        except engine.CombatError:
            if not script.db.unsupported_notice:
                script.db.unsupported_notice = True
                transaction.on_commit(
                    lambda: services.emit(
                        script.obj,
                        None,
                        "Unsupported combat state version; fight suspended for staff restoration or migration.",
                    )
                )
            return
        if state["ended"]:
            return
        before = services.clone(state)
        notices = []
        for row in state["participants"].values():
            if row["status"] != "active":
                continue
            obj = ObjectDB.objects.filter(pk=row["id"]).first()
            absent = obj is None or obj.location != script.obj
            if obj and row["npc"]:
                record = services.npc_record(obj)
                controller = services.owner(obj)
                if record is None or controller is None:
                    absent = True
                else:
                    from evennia_npcs.services import can_play

                    absent = absent or not can_play(controller, record.blueprint)
            last = row.get("last_activity", now)
            idle = conf.get("RP_COMBAT_IDLE_SECONDS")
            absent = absent or (idle > 0 and now - last >= idle)
            if not absent:
                if row.pop("absent", None):
                    notices.append(f"{row['name']} is present again and may continue.")
                continue
            # Cleanup only unaccepted packets. Accepted reactions survive and
            # will resolve with their frozen inputs when their peers finish.
            for token in list(row["incoming"]):
                exchange = engine.get_exchange(state, token)
                if row["id"] not in exchange["reactions"]:
                    engine.cancel(state, row["id"], token)
            if row["outgoing"]:
                exchange = state["exchanges"][row["outgoing"]]
                if exchange["phase"] == "press":
                    engine.finish_exchange(state, exchange)
                elif exchange["phase"] == "waiting":
                    token = f"{exchange['id']}:{exchange['hit']}"
                    for target in exchange["targets"]:
                        if (
                            target not in exchange["reactions"]
                            and target not in exchange["canceled"]
                        ):
                            engine.cancel(state, target, token)
            if not row["incoming"] and not row["outgoing"]:
                engine.fade(state, row["id"])
                row.pop("absent", None)
                notices.append(
                    f"{row['name']} Faded after absence, idle time or NPC control loss; retained contributions and build preserved."
                )
            else:
                if not row.get("absent"):
                    notices.append(
                        f"{row['name']} is absent with an accepted reaction; it remains committed while peers finish or staff recover the exchange."
                    )
                row["absent"] = True
        if state == before:
            return
        journal, operations = (
            services.clone(script.db.journal),
            services.clone(script.db.operations),
        )
        operation_id = str(uuid.uuid4())
        summary = " ".join(notices) or "Absence cleanup canceled unaccepted packets."
        sequence = len(journal) + 1
        journal.append(
            {
                "sequence": sequence,
                "operation": operation_id,
                "actor": None,
                "at": datetime.now(UTC).isoformat(),
                "summary": summary,
                "before": before,
                "superseded": False,
            }
        )
        operations[operation_id] = {
            "sequence": sequence,
            "result": summary,
            "superseded": False,
            "actor": None,
            "label": summary,
        }
        script.db.state, script.db.journal, script.db.operations = state, journal, operations
        services.synchronize_locks(script, state)
        services.notify_membership(script, before, state, None)
        room = script.obj
        transaction.on_commit(lambda: services.emit(room, None, summary))
        for key, exchange in state["exchanges"].items():
            old_count = len(before["exchanges"].get(key, {}).get("outcomes", []))
            if len(exchange["outcomes"]) > old_count:
                text = services.render_outcomes(state, exchange, old_count)
                transaction.on_commit(lambda text=text: services.emit(room, None, text))


def note_pose(sender, character=None, npc=None, pose_type="pose", **kwargs):
    character = character or npc
    if character is None or character.location is None or pose_type == "ooc":
        return
    scripts = character.location.scripts.get("rp_combat_coordinator")
    if not scripts:
        return
    script = scripts[0]
    with transaction.atomic():
        ScriptDB.objects.select_for_update().get(pk=script.pk)
        script.attributes.reset_cache()
        state = services.clone(script.db.state)
        row = state["participants"].get(str(character.pk))
        if row and not state["ended"]:
            row["last_activity"], row["pose"] = time.time(), False
            script.db.state = state


def object_deleted(sender, instance, **kwargs):
    if not isinstance(instance, ObjectDB):
        return
    for script in ScriptDB.objects.filter(db_key="rp_combat_coordinator"):
        if str(instance.pk) in (script.db.state or {}).get("participants", {}):
            transaction.on_commit(lambda script=script: maintain(script))
