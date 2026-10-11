# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authorization, transactional persistence and optional partner seams.

All mechanical writes use execute(), which locks the Script row, copies its
state and commits a checkpoint plus result atomically. Messages follow commit.
"""

import json
import random
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime

from django.apps import apps
from django.db import transaction
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.utils.create import create_script

from evennia_links import runtime

from . import conf, engine, policies, tactics
from .data import TIERS, ActionView, Build, CombatError, Move
from .sources import snapshot


def plain(text, limit=200):
    from evennia.utils.ansi import strip_ansi

    return "".join(c for c in strip_ansi(str(text)) if c.isprintable())[:limit]


def clone(value):
    # Detach Evennia's mutable saver containers from their Attribute owner.
    from evennia.utils.dbserialize import deserialize

    return json.loads(json.dumps(deserialize(value)))


def staff(actor):
    return actor.locks.check_lockstring(actor, conf.get("RP_COMBAT_STAFF_LOCK"))


def require(actor, *, progress=False):
    if not runtime.get("RP_COMBAT_REVEALED"):
        raise CombatError("Combat is not available yet.")
    if actor.location is None:
        raise CombatError("Enter a room first.")
    if progress and runtime.get("RP_COMBAT_FROZEN"):
        raise CombatError("Combat is frozen. Inspection, cancellation and fade remain available.")


def coordinator(room, *, create=False):
    with transaction.atomic():
        ObjectDB.objects.select_for_update().get(pk=room.pk)
        script = room.scripts.get("rp_combat_coordinator")
        if script:
            return script[0]
        if create:
            return create_script("evennia_rp_combat.scripts.CombatCoordinator", obj=room)
    raise CombatError("No combat has been set up here. Use +combat/setup.")


def state_for(actor):
    require(actor)
    script = coordinator(actor.location)
    script.attributes.reset_cache()
    state = clone(script.db.state)
    validate_state(state)
    return state


def validate_state(state):
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise CombatError(
            "Unsupported combat state version; staff must restore or migrate this fight. No progress was applied."
        )


def npc_record(subject):
    if apps.is_installed("evennia_npcs"):
        from evennia_npcs.services import record_for

        return record_for(subject)
    return None


def authorize(actor, subject, *, cleanup=False, batch=False):
    if actor.location is None or subject.location != actor.location:
        raise CombatError("Combat participants must be in your room.")
    record = npc_record(subject)
    if record:
        from evennia_npcs import services as npcs
        from evennia_npcs.integrations import require_scene_access

        try:
            npcs.require(actor, write=not cleanup, cleanup=cleanup)
            batch_row = None
            marker = subject.attributes.get("build_lock", category="rp_combat")
            if marker:
                script = ScriptDB.objects.filter(pk=marker["fight"]).first()
                batch_row = script.db.state["participants"].get(str(subject.pk)) if script else None
            batch_allowed = (
                batch or (batch_row and batch_row.get("batch_controller") == actor.pk)
            ) and record.controller_id in (None, actor.pk)
            if record.controller_id != actor.pk and subject != actor and not batch_allowed:
                raise CombatError("Take authorized control of that NPC before directing it.")
            owner = record.controller if subject == actor else actor
            if owner is None or not npcs.can_play(owner, record.blueprint):
                raise CombatError("Your permission to portray this NPC has ended.")
            require_scene_access(subject, owner)
        except npcs.NPCError as exc:
            raise CombatError(str(exc)) from None
        return record
    if actor != subject:
        raise CombatError("Only that player can accept participation or direct their character.")
    return None


def owner(subject):
    record = npc_record(subject)
    if not record:
        return subject
    if record.controller:
        return record.controller
    marker = subject.attributes.get("build_lock", category="rp_combat")
    if marker:
        script = ScriptDB.objects.filter(pk=marker["fight"]).first()
        row = script.db.state["participants"].get(str(subject.pk)) if script else None
        if row and row.get("batch_controller"):
            return ObjectDB.objects.filter(pk=row["batch_controller"]).first()
    return None


def account(subject):
    controller = owner(subject)
    return (controller.account or controller.db.account) if controller else None


def ignored_by(subject, other):
    if not apps.is_installed("evennia_social"):
        return False
    own_account, other_account = account(subject), account(other)
    return bool(
        own_account and other_account and other_account.pk in (own_account.db.ignore_list or [])
    )


def interaction(first, second):
    """Private prompts to each ignore owner; caller gets a neutral refusal."""
    blocked = False
    for subject, other in ((first, second), (second, first)):
        if ignored_by(subject, other):
            controller = owner(subject)
            if controller:
                controller.msg(
                    "Someone you ignore is attempting a direct combat interaction. "
                    "+combat/unignore <character> removes the account-wide ignore, "
                    "including alts and channel filtering, until you turn it on again. "
                    "You may instead cancel an unaccepted incoming attack."
                )
            blocked = True
    if blocked:
        raise CombatError(
            "Direct interaction requires player confirmation. No resources were spent."
        )


def unignore(actor, other):
    """An explicit command with warning, never an automatic reaction side effect."""
    require(actor)
    own_account, other_account = account(actor), account(other)
    if own_account is None or other_account is None:
        raise CombatError("No account ignore entry is available for these characters.")
    with transaction.atomic():
        from evennia.accounts.models import AccountDB

        AccountDB.objects.select_for_update().get(pk=own_account.pk)
        own_account.attributes.reset_cache()
        ignored = list(own_account.db.ignore_list or [])
        if other_account.pk not in ignored:
            raise CombatError("You are not ignoring that account.")
        ignored.remove(other_account.pk)
        own_account.db.ignore_list = ignored
    actor.msg(
        "Ignore removed account-wide, including alts and channel filtering. "
        "It stays off until you turn it on again with +ignore."
    )


def identity(subject):
    record = npc_record(subject)
    if record:
        from evennia_npcs.services import attribution

        return plain(attribution(subject))
    return plain(subject.key)


def emit(room, actor, text):
    """Mechanics are SYSTEM entries only, never posing or tracker activity."""
    text = "[Combat] " + text
    room.msg_contents(("{combat_text}", {"type": "rp_combat"}), mapping={"combat_text": text})
    if apps.is_installed("evennia_scenes"):
        Scene = apps.get_model("evennia_scenes", "Scene")
        scene = Scene.objects.filter(
            pk=getattr(room, "active_scene_id", None), status__in=("open", "active")
        ).first()
        if scene:
            # Preserve scene privacy; an actor may not inject into a private
            # scene without the same access required for NPC portrayal.
            if (
                scene.privacy != "public"
                and actor is not None
                and not (
                    staff(actor)
                    or scene.creator_id == actor.pk
                    or scene.participants.filter(character=actor, is_invited=True).exists()
                )
            ):
                return
            apps.get_model("evennia_scenes", "LogEntry").create_entry(
                scene, actor, text, log_type="system"
            )


def synchronize_locks(script, state):
    for key, row in state["participants"].items():
        obj = ObjectDB.objects.filter(pk=key).first()
        if obj:
            if state["ended"]:
                marker = obj.attributes.get("build_lock", category="rp_combat")
                if marker and marker.get("fight") == script.pk:
                    obj.attributes.remove("build_lock", category="rp_combat")
            else:
                obj.attributes.add(
                    "build_lock",
                    {"fight": script.pk, "correction": row["correction"]},
                    category="rp_combat",
                )


def notify_membership(script, before, state, actor_id):
    """Publish the same post-commit seam for actions, maintenance and rollback."""
    from .signals import membership_changed

    for key in before["participants"].keys() | state["participants"].keys():
        old = before["participants"].get(key)
        row = state["participants"].get(key)
        status = "ended" if row is None or state["ended"] else row["status"]
        old_status = "ended" if old is None or before["ended"] else old["status"]
        if status != old_status:
            transaction.on_commit(
                lambda key=key, status=status: membership_changed.send_robust(
                    sender=type(script),
                    character_id=int(key),
                    fight_id=script.pk,
                    status=status,
                    actor_id=actor_id,
                )
            )


def execute(actor, label, operation, *, progressing=True, operation_id=None, storyteller=False):
    require(actor, progress=progressing)
    room = actor.location
    script = coordinator(room)
    operation_id = operation_id or str(uuid.uuid4())
    with transaction.atomic():
        ScriptDB.objects.select_for_update().get(pk=script.pk)
        script.attributes.reset_cache()
        state = clone(script.db.state)
        validate_state(state)
        journal, operations = clone(script.db.journal), clone(script.db.operations)
        if operation_id in operations:
            record = operations[operation_id]
            if record["superseded"]:
                raise CombatError("That operation was superseded by staff rollback.")
            if record.get("actor") != actor.pk or record.get("label") != label:
                raise CombatError("That operation identifier belongs to a different request.")
            return deepcopy(record["result"])
        before = clone(state)
        result = operation(state)
        for key, row in state["participants"].items():
            if key == str(actor.pk) or row.get("batch_controller") == actor.pk:
                row["last_activity"] = time.time()
        if (
            state["started"]
            and not state["ended"]
            and not any(p["incoming"] or p["outgoing"] for p in state["participants"].values())
        ):
            present = [
                p for p in state["participants"].values() if p["status"] == "active" and p["hp"] > 0
            ]
            if present and all(p["turns"] >= p["turn_limit"] for p in present):
                state["ended"] = True
                state["outcome"] = (
                    "Personal Turn Limits exhausted; assessment informs RP without imposing an outcome"
                )
        sequence = len(journal) + 1
        summary = f"{'Storyteller ' if storyteller else ''}{identity(actor)}: {plain(label, 500)} (sequence {sequence})."
        journal.append(
            {
                "sequence": sequence,
                "operation": operation_id,
                "actor": actor.pk,
                "at": datetime.now(UTC).isoformat(),
                "summary": summary,
                "before": before,
                "superseded": False,
            }
        )
        operations[operation_id] = {
            "sequence": sequence,
            "result": result,
            "superseded": False,
            "actor": actor.pk,
            "label": label,
        }
        script.db.state, script.db.journal, script.db.operations = state, journal, operations
        synchronize_locks(script, state)
        notify_membership(script, before, state, actor.pk)
        transaction.on_commit(lambda: emit(room, actor, summary))
        for key, exchange in state["exchanges"].items():
            prior = before["exchanges"].get(key)
            if prior is None or prior["hit"] != exchange["hit"]:
                text = render_declaration(state, exchange)
                transaction.on_commit(lambda text=text: emit(room, actor, text))
            old_count = len(before["exchanges"].get(key, {}).get("outcomes", []))
            if len(exchange["outcomes"]) > old_count:
                text = render_outcomes(state, exchange, old_count)
                transaction.on_commit(lambda text=text: emit(room, actor, text))
        return result


def setup(actor, *, reason="", operation_id=None):
    require(actor, progress=True)
    script = coordinator(actor.location, create=True)

    def operation(state):
        if state["participants"] and not state["ended"]:
            raise CombatError("This room already has an active fight.")
        epoch = state["epoch"] + 1
        state.clear()
        state.update(engine.new_state())
        state["epoch"] = epoch
        state["imbalance"] = plain(reason)
        return script.pk

    return execute(
        actor, f"set up combat. {reason}", operation, storyteller=True, operation_id=operation_id
    )


def npc_build(subject, record):
    from evennia_rp_rules.subjects import DictStatSource

    from .sources import from_source

    profile = getattr(record.blueprint, "combat_profile", None)
    if profile:
        npc_policy(profile)
    # NPC profile special_moves are authored definitions, not PC catalog rows.
    catalog = conf.get("RP_COMBAT_NPC_MOVES")
    moves = []
    for key in profile.special_moves if profile else ():
        if key not in catalog:
            raise CombatError(f"Unknown NPC special move identifier: {plain(key)}.")
        moves.append(Move.from_dict({**catalog[key], "key": key, "kind": "signature"}))
    abilities = []
    for key in record.blueprint.abilities:
        ability, _, tag = key.partition(":")
        abilities.append((ability, tag, 1))
    return from_source(
        DictStatSource(record.blueprint.stat_block), moves=moves, abilities=abilities
    )


def npc_policy(profile):
    if profile.boss_check_schedule:
        raise CombatError(
            "Boss Check schedules are not supported in combat 0.1; clear the schedule first."
        )
    policy = {
        **profile.reaction_policy,
        "target_policy": profile.target_policy,
        **({"action_weights": profile.action_weights} if profile.action_weights else {}),
    }
    tactics.validate(policy)
    return policy


def join(actor, side, *, subject=None, boss=1, turn_limit=None, batch=False, operation_id=None):
    subject = subject or actor
    record = authorize(actor, subject, batch=batch)
    build = npc_build(subject, record) if record else snapshot(subject)

    def operation(state):
        other_lock = subject.attributes.get("build_lock", category="rp_combat")
        if other_lock and other_lock.get("fight") != coordinator(actor.location).pk:
            raise CombatError("That character is still enrolled in another fight.")
        name = (
            f"{plain(subject.key)} (NPC, directed by {identity(actor)})"
            if batch and record
            else identity(subject)
        )
        row = engine.join(
            state,
            subject.pk,
            name,
            plain(side, 40),
            build,
            boss=boss,
            turn_limit=conf.get("RP_COMBAT_TURN_LIMIT") if turn_limit is None else turn_limit,
            npc=bool(record),
        )
        row["last_activity"] = time.time()
        if record:
            if batch:
                row["batch_controller"] = actor.pk
            profile = getattr(record.blueprint, "combat_profile", None)
            if profile:
                row["policy"] = npc_policy(profile)
        return row["id"]

    return execute(
        actor,
        f"{identity(subject)} explicitly joined side {plain(side, 40)}",
        operation,
        operation_id=operation_id,
    )


def template(actor, blueprint, side, *, boss=1, turn_limit=None):
    if not apps.is_installed("evennia_npcs"):
        raise CombatError("The optional NPC partner is not installed.")
    from evennia_npcs import services as npcs

    require(actor, progress=True)
    try:
        with transaction.atomic():
            record = npcs.spawn(actor, blueprint)
            subject = record.spawned_object
            join(actor, side, subject=subject, boss=boss, turn_limit=turn_limit, batch=True)
            execute(
                actor,
                f"attached template {plain(blueprint.name)} to side {plain(side)}",
                lambda state: state["templates"].setdefault(side, []).append(blueprint.pk),
                storyteller=True,
            )
            return subject
    except npcs.NPCError as exc:
        raise CombatError(str(exc)) from None


def auto_batch(actor, subjects):
    lines = []
    for subject in sorted(set(subjects), key=lambda obj: obj.pk):
        if npc_record(subject) is None:
            lines.append(f"{identity(subject)}: skipped; batches direct permitted NPCs only.")
            continue
        try:
            result = auto_act(actor, subject=subject)
            lines.append(f"{identity(subject)}: {result}")
        except CombatError as exc:
            lines.append(f"{identity(subject)}: {exc}")
    return "\n".join(lines)


def invite(actor, target, side):
    require(actor, progress=True)
    script = coordinator(actor.location)
    if target.location != actor.location:
        raise CombatError("Invite a character in this room.")
    with transaction.atomic():
        ScriptDB.objects.select_for_update().get(pk=script.pk)
        script.attributes.reset_cache()
        invitations = clone(script.db.invitations)
        invitations[str(target.pk)] = {"by": actor.pk, "side": plain(side, 40)}
        script.db.invitations = invitations
    target.msg(
        f"{identity(actor)} invites you to combat on side {plain(side, 40)}. "
        "Use +combat/join <side> to explicitly accept, or +combat/refuse. No attack has executed."
    )
    return (
        "Invitation sent; the attack has not been declared or paid. Declare again after acceptance."
    )


def refuse(actor):
    require(actor)
    script = coordinator(actor.location)
    with transaction.atomic():
        ScriptDB.objects.select_for_update().get(pk=script.pk)
        script.attributes.reset_cache()
        invitations = clone(script.db.invitations)
        invitations.pop(str(actor.pk), None)
        script.db.invitations = invitations
    actor.msg("Invitation refused. No attack executes and no resources are spent.")


def choose_move(row, key, *, action="attack", improvised=None):
    if improvised is not None:
        move = Move.from_dict({**improvised, "kind": "improvised"})
        from .integrations import validate_move

        validate_move(move.as_dict(), signature=False)
    elif key in TIERS:
        move = Move(
            key=key, name=key.title(), action=action, power=TIERS[key][0], accuracy=TIERS[key][1]
        )
    elif key in ("assist", "dispirit"):
        move = Move(key=key, name=key.title(), action=key)
    else:
        move = next((m for m in Build.from_dict(row["build"]).moves if m.key == key), None)
        if move is None:
            raise CombatError("Choose a standard tier or an equipped Signature key.")
    return move


def declare(
    actor,
    targets,
    key="balanced",
    *,
    subject=None,
    action="attack",
    bet="",
    burst=False,
    empower=False,
    domain="",
    improvised=None,
    rng=None,
    operation_id=None,
):
    subject = subject or actor
    authorize(actor, subject)
    state = state_for(actor)
    for target in targets:
        if str(target.pk) not in state["participants"]:
            return invite(actor, target, "opposition")

    def operation(state):
        for target in targets:
            interaction(subject, target)
            if target.location != actor.location:
                raise CombatError("Every target must be in this room.")
        row = engine.participant(state, subject.pk)
        move = choose_move(row, key, action=action, improvised=improvised)
        ex_id = engine.declaration(
            state,
            subject.pk,
            [t.pk for t in targets],
            move,
            (rng or random.SystemRandom()).randint(1, 100),
            bet=bet,
            burst=burst,
            empower=empower,
            domain=domain,
            domain_effects=conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
        )
        run_automatic(state, subject.location)
        return ex_id

    return execute(
        actor,
        f"{identity(subject)} declared {plain(key)} against {', '.join(identity(t) for t in targets)}",
        operation,
        operation_id=operation_id,
    )


def react(
    actor,
    token,
    kind,
    *,
    subject=None,
    counter="balanced",
    empower=False,
    domain="",
    operation_id=None,
):
    subject = subject or actor
    authorize(actor, subject)

    def operation(state):
        exchange = engine.get_exchange(state, token)
        attacker = ObjectDB.objects.filter(pk=exchange["actor"]).first()
        if attacker is None or attacker.location != actor.location:
            raise CombatError("The attacker has left. Cancel this unaccepted incoming attack.")
        interaction(subject, attacker)
        row = engine.participant(state, subject.pk)
        chosen = choose_move(row, counter) if kind == "overpower" else None
        engine.reaction(
            state,
            subject.pk,
            token,
            kind,
            counter=chosen,
            empower=empower,
            domain=domain,
            domain_effects=conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
        )
        return token

    return execute(
        actor,
        f"{identity(subject)} accepted {plain(kind)} for {plain(token)}",
        operation,
        operation_id=operation_id,
    )


def run_automatic(state, room):
    for row in state["participants"].values():
        if not row["auto"] or row["status"] != "active":
            continue
        subject = ObjectDB.objects.filter(pk=row["id"]).first()
        if subject is None or subject.location != room:
            continue
        if row["npc"]:
            controller = owner(subject)
            if controller is None:
                continue
            try:
                authorize(controller, subject)
            except CombatError:
                continue
        profile = row.get("policy", {}) if row["npc"] else tactics.profile(subject)
        for token in list(row["incoming"]):
            exchange = engine.get_exchange(state, token)
            if row["id"] in exchange["reactions"]:
                continue
            attacker = ObjectDB.objects.filter(pk=exchange["actor"]).first()
            if attacker is None or ignored_by(subject, attacker) or ignored_by(attacker, subject):
                continue
            view = engine.reaction_view(state, row["id"], token)
            kind, counter = policies.auto_react(
                view,
                appetite=profile.get("appetite", "balanced"),
                preferred=profile.get("preferred_reaction", ""),
                preferred_moves=profile.get("preferred_moves", []),
            )
            engine.reaction(
                state,
                row["id"],
                token,
                kind,
                counter=counter if kind == "overpower" else None,
                domain_effects=conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
            )


def auto_act(actor, *, subject=None, rng=None, operation_id=None):
    subject = subject or actor
    authorize(actor, subject)
    rng = rng or random.SystemRandom()

    def operation(state):
        row = engine.active(state, subject.pk)
        public = [
            p
            for p in state["participants"].values()
            if p["status"] == "active"
            and p["hp"] > 0
            and p["id"] != row["id"]
            and not p["correction"]
        ]
        candidates = tuple((int(p["id"]), p["hp"]) for p in public if p["side"] != row["side"])
        allies = tuple((int(p["id"]), p["hp"]) for p in public if p["side"] == row["side"])
        profile = row.get("policy", {}) if row["npc"] else tactics.profile(subject)
        # Policies see own build plus public HP. Side legality is filtered
        # after selecting an action, with no extra target information exposed.
        provoker = row["conditions"].get("provoked", {}).get("source")
        target_id, move, bet = policies.auto_act(
            ActionView(
                Build.from_dict(row["build"]),
                candidates,
                row["reserves"],
                allies,
                int(provoker) if provoker else None,
                row["hp"],
            ),
            rng=rng,
            appetite=profile.get("rps_appetite", "balanced"),
            target_policy=profile.get("target_policy", "random"),
            weights=profile.get("action_weights") or None,
        )
        target = engine.participant(state, target_id)
        target_obj = ObjectDB.objects.filter(pk=target["id"]).first()
        if target_obj is None or target_obj.location != actor.location:
            raise CombatError("That target has left the room.")
        interaction(subject, target_obj)
        ex_id = engine.declaration(
            state,
            subject.pk,
            [target["id"]],
            move,
            rng.randint(1, 100),
            bet=bet,
            domain_effects=conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
        )
        run_automatic(state, actor.location)
        return ex_id

    return execute(
        actor,
        f"{identity(subject)} explicitly invoked Auto-Act once",
        operation,
        operation_id=operation_id,
    )


def control(
    actor, operation, *, subject=None, argument=None, reason="", rng=None, operation_id=None
):
    subject = subject or actor
    cleanup = operation in ("cancel", "fade", "withdraw", "posed")
    authorize(actor, subject, cleanup=cleanup)

    def change(state):
        row = engine.participant(state, subject.pk)
        if operation == "cancel":
            engine.cancel(state, subject.pk, argument)
        elif operation in ("fade", "withdraw"):
            engine.fade(state, subject.pk, withdraw=operation == "withdraw")
        elif operation == "posed":
            row["pose"] = False
        elif operation == "auto":
            if argument not in ("on", "off"):
                raise CombatError("Choose +combat/auto on or off explicitly.")
            row["auto"] = argument == "on"
            if row["auto"]:
                run_automatic(state, actor.location)
        elif operation == "unlock":
            engine.correction(state, subject.pk)
        elif operation == "relock":
            record = npc_record(subject)
            engine.correction(
                state, subject.pk, build=npc_build(subject, record) if record else snapshot(subject)
            )
        elif operation in ("press", "stop"):
            if operation == "press":
                exchange = state["exchanges"].get(row["outgoing"])
                if exchange:
                    for target_id in exchange["targets"]:
                        target = ObjectDB.objects.filter(pk=target_id).first()
                        if target is None or target.location != actor.location:
                            raise CombatError("That target has left the room; stop the Burst.")
                        interaction(subject, target)
            engine.press(
                state,
                subject.pk,
                (rng or random.SystemRandom()).randint(1, 100),
                stop=operation == "stop",
                empower=argument == "empower",
            )
            run_automatic(state, actor.location)
        elif operation == "cap":
            engine.reduce_cap(state, subject.pk, argument)
        elif operation == "acceptcap":
            if row["cap_request"] is None:
                raise CombatError("No pending Turn Limit request.")
            engine.reduce_cap(state, subject.pk, row["cap_request"])
        elif operation == "refusecap":
            row["cap_request"] = None
        else:
            raise CombatError("Unknown combat control.")
        return operation

    return execute(
        actor,
        f"{identity(subject)} used {plain(operation)} {plain(argument or '')}. {plain(reason)}",
        change,
        progressing=not cleanup,
        operation_id=operation_id,
    )


def read(actor, token, domain, *, subject=None, operation_id=None):
    subject = subject or actor
    authorize(actor, subject)

    def operation(state):
        row = engine.active(state, subject.pk)
        exchange = engine.get_exchange(state, token)
        if token not in row["incoming"] or row["id"] in exchange["reactions"]:
            raise CombatError("Read before accepting your incoming reaction.")
        if conf.get("RP_COMBAT_DOMAIN_EFFECTS").get(domain) != "read" or not engine.has_domain(
            Build.from_dict(row["build"]), domain
        ):
            raise CombatError("Equip the Insight/Read domain first.")
        attacker = ObjectDB.objects.filter(pk=exchange["actor"]).first()
        if attacker is None:
            raise CombatError("The attacker has left; cancel the unaccepted incoming attack.")
        interaction(subject, attacker)
        readers = exchange.setdefault("readers", [])
        if row["id"] not in readers:
            if row["reserves"] < 1:
                raise CombatError("Read costs 1 Reserve.")
            row["reserves"] -= 1
            readers.append(row["id"])
        return f"Incoming {token}: RPS {exchange['bet'] or 'none'}. No reaction has been accepted."

    return execute(
        actor,
        f"{identity(subject)} used Read on {plain(token)}",
        operation,
        operation_id=operation_id,
    )


def storyteller(actor, operation, *, target=None, value=None, reason="", operation_id=None):
    """Culturally open interventions; PC enrollment/cap acceptance stay personal."""
    if operation == "boss":
        raise CombatError(
            "Set Boss Mode when joining; live reconfiguration and Boss Checks are not in 0.1."
        )

    def change(state):
        row = engine.participant(state, target.pk) if target else None
        if row and row["npc"]:
            authorize(actor, target, batch=True)
        if operation == "pause":
            state["paused"] = True
        elif operation == "resume":
            state["paused"] = False
        elif operation == "end":
            if any(p["incoming"] or p["outgoing"] for p in state["participants"].values()):
                raise CombatError("Clear pending exchanges before ending combat.")
            state["ended"] = True
            state["outcome"] = plain(reason) or "Ended by agreement; no narrative outcome imposed"
        elif operation == "imbalance":
            state["imbalance"] = plain(reason)
        elif operation == "vitality" and row:
            row["hp"] = math_clamp(0, row["max_hp"], value)
        elif operation == "spirit" and row:
            row["spirit"] = math_clamp(-1000, 2000, value)
        elif operation == "requestcap" and row:
            if type(value) is not int or not max(1, row["turns"]) <= value <= row["turn_limit"]:
                raise CombatError(
                    "Choose a lower personal Turn Limit within the participant's used/current caps."
                )
            row["cap_request"] = value
        elif operation == "condition" and row:
            if value not in (
                "grappled",
                "poisoned",
                "warded",
                "vulnerable",
                "endure",
                "slip_inside",
            ):
                raise CombatError("Choose a supported named condition.")
            engine.condition(
                row,
                value,
                3
                if value == "poisoned"
                else 20
                if value == "vulnerable"
                else 10
                if value == "grappled"
                else 1,
                2,
            )
        elif operation == "clearcondition" and row:
            row["conditions"].pop(value, None)
        else:
            raise CombatError("Unknown storyteller operation or missing target.")
        return operation

    return execute(
        actor,
        f"{operation} {identity(target) if target else ''} {plain(value or '')}. {plain(reason)}",
        change,
        progressing=operation not in ("pause", "end"),
        storyteller=True,
        operation_id=operation_id,
    )


def math_clamp(low, high, value):
    if type(value) is not int:
        raise CombatError("Supply a whole resource value.")
    return max(low, min(high, value))


def rollback(actor, sequence, reason):
    require(actor)
    if not staff(actor):
        raise CombatError("Only staff may roll back accepted or resolved combat.")
    if not plain(reason).strip():
        raise CombatError("Staff rollback requires a visible reason.")
    script = coordinator(actor.location)
    with transaction.atomic():
        ScriptDB.objects.select_for_update().get(pk=script.pk)
        script.attributes.reset_cache()
        journal, operations = clone(script.db.journal), clone(script.db.operations)
        checkpoint = next(
            (item for item in journal if item["sequence"] == sequence and not item["superseded"]),
            None,
        )
        if checkpoint is None:
            raise CombatError("Choose a retained, unsuperseded sequence.")
        current = clone(script.db.state)
        restored = clone(checkpoint["before"])
        restored["epoch"] = current["epoch"] + 1
        # Re-key pending exchange tokens. Old commands cannot act on restored
        # state, even if their original exchange number still exists.
        remap = {key: f"{restored['epoch']}.{key.split('.')[-1]}" for key in restored["exchanges"]}
        restored["exchanges"] = {
            remap[key]: {**ex, "id": remap[key]} for key, ex in restored["exchanges"].items()
        }
        for row in restored["participants"].values():
            row["incoming"] = [
                f"{remap[t.split(':')[0]]}:{t.split(':')[1]}" for t in row["incoming"]
            ]
            row["outgoing"] = remap.get(row["outgoing"])
        reconciliation = []
        for key, row in restored["participants"].items():
            subject = ObjectDB.objects.filter(pk=key).first()
            try:
                live = (
                    npc_build(subject, npc_record(subject))
                    if subject and row["npc"]
                    else snapshot(subject)
                    if subject
                    else None
                )
                if live is None or live.as_dict() != row["build"]:
                    reconciliation.append(row["name"])
            except (CombatError, ValueError):
                reconciliation.append(row["name"])
        if reconciliation:
            restored["paused"] = True
        for item in journal:
            if item["sequence"] >= sequence:
                item["superseded"] = True
                operations[item["operation"]]["superseded"] = True
        # Remove locks for participants introduced after the checkpoint.
        removed = {
            k: p for k, p in current["participants"].items() if k not in restored["participants"]
        }
        synchronize_locks(script, {"participants": removed, "ended": True})
        script.db.state, script.db.journal, script.db.operations = restored, journal, operations
        synchronize_locks(script, restored)
        summary = f"Staff {identity(actor)} rolled the whole fight back before sequence {sequence}: {plain(reason)}. Pending tokens changed."
        if reconciliation:
            summary += (
                " Fight paused: reconcile external build changes/deletions for "
                + ", ".join(reconciliation)
                + "."
            )
        operation_id = str(uuid.uuid4())
        journal.append(
            {
                "sequence": len(journal) + 1,
                "operation": operation_id,
                "actor": actor.pk,
                "at": datetime.now(UTC).isoformat(),
                "summary": summary,
                "before": current,
                "superseded": False,
            }
        )
        operations[operation_id] = {
            "sequence": len(journal),
            "result": "rollback",
            "superseded": False,
            "actor": actor.pk,
            "label": summary,
        }
        script.db.journal, script.db.operations = journal, operations
        notify_membership(script, current, restored, actor.pk)
        transaction.on_commit(lambda: emit(actor.location, actor, summary))


def render_declaration(state, exchange):
    """Only public move facts; a flavor hook never participates in resolution."""
    move = Move.from_dict(exchange["move"])
    actor = engine.participant(state, exchange["actor"])
    flavor = ""
    path = conf.get("RP_COMBAT_WEAPON_FLAVOR")
    if path:
        from evennia_rp_rules._config import resolve_dotted

        try:
            subject = ObjectDB.objects.filter(pk=actor["id"]).first()
            flavor = plain(resolve_dotted(path)(subject), 120)
        except (ValueError, TypeError, LookupError, AttributeError):
            flavor = ""
    suffix = f" Weapon flavor: {flavor}." if flavor else ""
    fallbacks = []
    if "long_range" in move.effects or exchange["domain_effect"] == "pinpoint":
        fallbacks.append("Party cover/formation is unavailable; range/Pinpoint has no cover effect")
    if exchange["domain_effect"] == "encore":
        fallbacks.append("Encore uses its single-target fallback without Party")
    return (
        f"{actor['name']}: {exchange['id']} hit {exchange['hit']}, {move.name} ({move.action}); "
        f"authored Power {move.power}, Accuracy {move.effective_accuracy}; "
        f"Effects {', '.join(move.effects) or 'none'}; element/style {move.element or 'none'}. "
        f"{plain(move.wording, 240)}{suffix} " + "; ".join(fallbacks)
    ).strip()


def render_outcomes(state, exchange, start=0):
    actor = engine.participant(state, exchange["actor"])
    lines = [f"{actor['name']}: {exchange['id']} resolved. RPS {exchange['bet'] or 'none'}."]
    for outcome in exchange["outcomes"][start:]:
        target = engine.participant(state, outcome["target"])
        if "reaction" in outcome:
            lines.append(
                f"{target['name']}: {outcome['reaction']} {'succeeded' if outcome['success'] else 'glanced' if outcome['glancing'] else 'failed'}, "
                f"d100 {outcome['draw']}, threshold {outcome['chance']}; "
                f"lost {outcome['damage']} Vitality, counter dealt {outcome['counter_damage']}."
            )
        else:
            lines.append(
                f"{target['name']}: Spirit change {outcome['spirit'] / 100:+.2f}; healed {outcome['healing']} Vitality."
            )
    if exchange["phase"] == "press":
        lines.append("Burst remains open: actor may +combat/press or +combat/stop.")
    return "\n".join(lines)


def result(actor, exchange_id):
    """Recover committed public results after reconnect without replaying writes."""
    state = state_for(actor)
    exchange = state["exchanges"].get(exchange_id)
    if exchange is None:
        raise CombatError("Choose a current exchange ID from +combat or +combat/journal.")
    if not exchange["outcomes"]:
        return "No committed outcomes yet; waiting for reactions or cancellation."
    return render_outcomes(state, exchange)


def render(actor, *, subject=None):
    state = state_for(actor)
    lines = [
        f"Combat: {'ended' if state['ended'] else 'paused' if state['paused'] else 'active'}. "
        f"Personal turns; no global rounds. {plain(state['imbalance'])}"
    ]
    for row in state["participants"].values():
        lines.append(
            f"{row['name']} [{row['side']}]: {row['hp']}/{row['max_hp']} Vitality; "
            f"turns {row['turns']}/{row['turn_limit']}, allowance {row['actions_left']}; {row['status']}; "
            f"{'acted' if row['clock'] else 'has not acted'}; incoming {len(row['incoming'])}."
        )
    own = state["participants"].get(str((subject or actor).pk))
    if own:
        if subject and subject != actor:
            authorize(actor, subject, cleanup=True)
        lines.append(
            f"Your resources: Reserves {own['reserves']}/5; Spirit {own['spirit'] / 100:.2f}; "
            f"Transcendence {own['transcendence']}/100; Resist pressure {own['pressure']}/30; "
            f"Auto-Resolve {'on' if own['auto'] else 'off'}; pose {'owed' if own['pose'] else 'clear'}; "
            f"build {'unlocked for correction' if own['correction'] else 'frozen'}."
        )
        if own["cap_request"]:
            lines.append(
                f"Requested personal Turn Limit {own['cap_request']}: +combat/acceptcap or /refusecap."
            )
        for information in own.get("information", {}).values():
            traits = ", ".join(f"{key}: {tag}" for key, tag in information["traits"]) or "none"
            flaws = ", ".join(f"{key}: {tag}" for key, tag in information["flaws"]) or "none"
            lines.append(
                f"Analyzed {information['name']}: resistance/vulnerability {traits}; combat Flaws {flaws}."
            )
        for token in own["incoming"]:
            exchange = engine.get_exchange(state, token)
            view = engine.reaction_view(state, own["id"], token)
            lines.append(
                f"Incoming {token}: {engine.participant(state, exchange['actor'])['name']}, "
                f"{exchange['move']['action']}; Power {view.power}, Accuracy {view.accuracy}, "
                f"Spirit {view.spirit / 100:.2f}; "
                f"{'reaction accepted' if own['id'] in exchange['reactions'] else 'choose Evade, Resist, Overpower or cancel'}."
            )
    for exchange in list(state["exchanges"].values())[-5:]:
        lines.append(
            f"Exchange {exchange['id']}: {exchange['phase']}; +combat/result {exchange['id']} for committed outcomes."
        )
    from fractions import Fraction

    lines.append(
        "Combat Assessment (retained contributions): "
        + "; ".join(
            f"{side}: {max(0, min(100, float(Fraction(value)) * 100)):.1f}%"
            if not value.startswith("unrated")
            else f"{side}: {value}"
            for side, value in engine.assessment(state).items()
        )
    )
    return "\n".join(lines)


def odds(actor, token, *, subject=None):
    """Public neutral estimates; hidden RPS and committed draws stay hidden."""
    from fractions import Fraction

    from . import arithmetic

    subject = subject or actor
    authorize(actor, subject, cleanup=True)
    state = state_for(actor)
    row = engine.participant(state, subject.pk)
    if token not in row["incoming"]:
        raise CombatError("Choose a token in your own incoming queue.")
    view = engine.reaction_view(state, subject.pk, token)
    if not view.estimates:
        return "Misdirected: your next reaction has no estimate. Every reaction remains available."
    incoming = Build(tuple((key, "0") for key, score in view.build.scores))
    move = Move(action=view.action)
    lines = [
        f"Incoming {plain(token)}: neutral RPS estimates; unseen offensive scores use a neutral damage estimate."
    ]
    for reaction in ("evade", "resist", "overpower"):
        result = arithmetic.resolve(
            incoming,
            view.build,
            move,
            reaction,
            1,
            power=view.power,
            accuracy=view.accuracy,
            spirit=view.spirit,
            defender_spirit=view.spirit_self,
            pressure=view.pressure,
            penalty=Fraction(dict(view.penalties)[reaction]),
            bonus=Fraction(dict(view.bonuses)[reaction]),
        )
        lines.append(
            f"{reaction.title()}: {result.chance}% success; successful incoming damage estimate {result.damage}. "
            + ("Standard balanced counter." if reaction == "overpower" else "")
        )
    return "\n".join(lines)
