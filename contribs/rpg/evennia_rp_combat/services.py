# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authorization, transactional persistence and optional partner seams.

Every mechanical write goes through execute(): it locks the room's open
Fight row, runs the engine on a copy of its state and, in one transaction,
saves the new state and appends a single FightEntry holding the state before
the operation and its result. History is append-only, so a long fight never
rewrites its journal. Messages follow commit.

Player actions (+combat) act only on your own character or an NPC you may
direct. Storyteller actions (+combatstory) are open to everyone and publicly
attributed; a change to another player's character is a request that player
accepts or declines, and ending a fight needs the present players' agreement.
"""

import hashlib
import json
import random
import time
import uuid
from copy import deepcopy

from django.apps import apps
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_script

from evennia_links import runtime

from . import conf, engine, partners, policies, tactics
from .data import TIERS, ActionView, Build, CombatError, Move
from .sources import snapshot
from .state import upgrade

MAINTENANCE_KEY = "rp_combat_maintenance"


def plain(text, limit=200):
    from evennia.utils.ansi import strip_ansi

    return "".join(c for c in strip_ansi(str(text)) if c.isprintable())[:limit]


def clone(value):
    """A detached JSON copy; fight state is plain JSON by construction."""
    return json.loads(json.dumps(value))


def notice(state, text):
    """Append to this operation's public summary. Never persisted in state."""
    state.setdefault("notices", []).append(plain(text, 400))


def staff(actor):
    return actor.locks.check_lockstring(actor, conf.get("RP_COMBAT_STAFF_LOCK"))


def require(actor, *, progress=False):
    if not runtime.get("RP_COMBAT_REVEALED"):
        raise CombatError("Combat is not available yet.")
    if actor.location is None:
        raise CombatError("Enter a room first.")
    if progress and runtime.get("RP_COMBAT_FROZEN"):
        raise CombatError("Combat is frozen. Inspection, cancellation and fade remain available.")


def _fights():
    from .models import Fight

    return Fight


def open_fight(room):
    Fight = _fights()
    fight = Fight.objects.filter(room=room, status=Fight.OPEN).first() if room else None
    if fight is None:
        raise CombatError("No combat has been set up here. Use +combat/setup.")
    return fight


def current_fight(room):
    """The room's open fight, else the one that most recently ended here."""
    Fight = _fights()
    here = Fight.objects.filter(room=room) if room else Fight.objects.none()
    fight = (
        here.filter(status=Fight.OPEN).first()
        or here.filter(status=Fight.ENDED).order_by("-closed_at", "-pk").first()
    )
    if fight is None:
        raise CombatError("No combat has been set up here. Use +combat/setup.")
    return fight


def state_for(actor):
    require(actor)
    return load(current_fight(actor.location))


def digest(build):
    canonical = json.dumps(build, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hydrate(fight, state):
    """Replace each participant's build digest with its frozen build, in place."""
    from .models import FightBuild

    state = upgrade(state)
    rows = [row for row in state["participants"].values() if "build_id" in row]
    builds = dict(
        FightBuild.objects.filter(
            fight=fight, digest__in={row["build_id"] for row in rows}
        ).values_list("digest", "build")
    )
    for row in rows:
        row["build"] = builds[row.pop("build_id")]
    return state


def stored(fight, state):
    """A copy for storage: builds become digests of rows saved once per fight."""
    from .models import FightBuild

    out = dict(state, participants={})
    for key, row in state["participants"].items():
        row = dict(row)
        if "build" in row:
            build = row.pop("build")
            row["build_id"] = digest(build)
            FightBuild.objects.get_or_create(
                fight=fight, digest=row["build_id"], defaults={"build": build}
            )
        out["participants"][key] = row
    return out


def load(fight):
    """The fight's validated state with builds in place, detached from the row."""
    state = clone(fight.state)
    return hydrate(fight, state)


def validate_state(state):
    return upgrade(state)


def ensure_maintenance():
    """One game-wide ticker cleans up absence across every open fight."""
    from evennia.scripts.models import ScriptDB

    if not ScriptDB.objects.filter(db_key=MAINTENANCE_KEY).exists():
        create_script(
            "evennia_rp_combat.scripts.CombatMaintenance", key=MAINTENANCE_KEY, persistent=True
        )


def room_row(subject):
    """The subject's row in the open fight where it currently stands."""
    if subject is None or subject.location is None:
        return None
    Fight = _fights()
    fight = Fight.objects.filter(room=subject.location, status=Fight.OPEN).first()
    return fight.state.get("participants", {}).get(str(subject.pk)) if fight else None


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
            batch_row = room_row(subject)
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
    row = room_row(subject)
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
    if room is None:
        return
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


def synchronize_locks(fight, state, *, release=()):
    """Freeze sheets only while a character is active in an open fight.

    Fading, withdrawing, shelving and ending release the sheet. The build
    frozen for the fight stays in its row, so a rejoin restores it exactly
    whatever happened to the sheet in between.
    """
    closed = fight.status != fight.OPEN or state["ended"]
    for key, row in state["participants"].items():
        obj = ObjectDB.objects.filter(pk=key).first()
        if obj is None:
            continue
        marker = obj.attributes.get("build_lock", category="rp_combat")
        if not closed and row["status"] == "active":
            wanted = {"fight": fight.pk, "correction": row["correction"]}
            if marker is None or dict(marker) != wanted:
                obj.attributes.add("build_lock", wanted, category="rp_combat")
        elif marker and marker.get("fight") == fight.pk:
            obj.attributes.remove("build_lock", category="rp_combat")
    for key in release:
        obj = ObjectDB.objects.filter(pk=key).first()
        marker = obj.attributes.get("build_lock", category="rp_combat") if obj else None
        if marker and marker.get("fight") == fight.pk:
            obj.attributes.remove("build_lock", category="rp_combat")


def active_elsewhere(subject, fight_pk):
    """True while the subject is active (sheet frozen) in another open fight."""
    marker = subject.attributes.get("build_lock", category="rp_combat")
    if not marker or marker.get("fight") == fight_pk:
        return False
    Fight = _fights()
    other = Fight.objects.filter(pk=marker["fight"], status=Fight.OPEN).first()
    row = other.state.get("participants", {}).get(str(subject.pk)) if other else None
    return bool(row and row["status"] == "active")


def notify_membership(fight, before, state, actor_id):
    """Publish the same post-commit seam for actions, maintenance and rollback."""
    from .signals import membership_changed

    closed = fight.status != fight.OPEN
    for key in before["participants"].keys() | state["participants"].keys():
        old = before["participants"].get(key)
        row = state["participants"].get(key)
        status = "ended" if row is None or state["ended"] else row["status"]
        old_status = "ended" if old is None or before["ended"] else old["status"]
        if status != old_status or (closed and status == "active"):
            transaction.on_commit(
                lambda key=key, status=status: membership_changed.send_robust(
                    sender=type(fight),
                    character_id=int(key),
                    fight_id=fight.pk,
                    status=status,
                    actor_id=actor_id,
                )
            )


def next_sequence(fight):
    return (fight.entries.aggregate(top=Max("sequence"))["top"] or 0) + 1


def commit(
    fight,
    before,
    state,
    *,
    actor,
    label,
    operation_id,
    result,
    summary,
    sequence,
    announce_exchanges=True,
    release=(),
):
    """Save state and append one journal entry; caller holds the row lock."""
    from .models import FightEntry

    notes = state.pop("notices", [])
    if notes:
        summary = f"{summary} {' '.join(plain(note, 400) for note in notes)}"
    FightEntry.objects.create(
        fight=fight,
        sequence=sequence,
        operation=operation_id,
        actor_id=getattr(actor, "pk", None),
        label=plain(label, 500),
        summary=summary,
        before=stored(fight, before),
        result=result,
    )
    if state["ended"] and fight.status == fight.OPEN:
        fight.status, fight.closed_at = fight.ENDED, timezone.now()
    partners.emit(state, partners.Event("state_changed", str(getattr(actor, "pk", "")), "", 0))
    fight.state = stored(fight, state)
    fight.save()
    synchronize_locks(fight, state, release=release)
    notify_membership(fight, before, state, getattr(actor, "pk", None))
    room = fight.room
    transaction.on_commit(lambda: emit(room, actor, summary))
    if announce_exchanges:
        for key, exchange in state["exchanges"].items():
            prior = before["exchanges"].get(key)
            if prior is None or prior["hit"] != exchange["hit"]:
                text = render_declaration(state, exchange)
                transaction.on_commit(lambda text=text: emit(room, actor, text))
            old_count = len((prior or {}).get("outcomes", []))
            if len(exchange["outcomes"]) > old_count:
                text = render_outcomes(state, exchange, old_count)
                transaction.on_commit(lambda text=text: emit(room, actor, text))
    return summary


def execute(
    actor,
    label,
    operation,
    *,
    progressing=True,
    operation_id=None,
    storyteller=False,
    subject=None,
    fight=None,
    close=None,
):
    require(actor, progress=progressing)
    room = actor.location
    Fight = _fights()
    fight_pk = (fight or open_fight(room)).pk
    operation_id = operation_id or str(uuid.uuid4())
    with transaction.atomic():
        fight = Fight.objects.select_for_update().get(pk=fight_pk)
        prior = fight.entries.filter(operation=operation_id).first()
        if prior is not None:
            if prior.superseded:
                raise CombatError("That operation was superseded by staff rollback.")
            if prior.actor_id != actor.pk or prior.label != plain(label, 500):
                raise CombatError("That operation identifier belongs to a different request.")
            return deepcopy(prior.result)
        if fight.status != Fight.OPEN or fight.room_id != room.pk:
            raise CombatError("That fight is no longer open in this room.")
        state = load(fight)
        before = clone(state)
        # Acting from this room proves presence for the actor and for the
        # character it directs, so neither stays marked absent or goes idle.
        touched = {str(actor.pk)}
        if subject is not None and subject.location == room:
            touched.add(str(subject.pk))
        for key in touched & state["participants"].keys():
            state["participants"][key].pop("absent", None)
        result = operation(state)
        # Any change that left someone at zero voids what they can't answer.
        engine.settle(state)
        for key, row in state["participants"].items():
            if key in touched or row.get("batch_controller") == actor.pk:
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
        if close:
            fight.status, fight.closed_at = close, timezone.now()
        sequence = next_sequence(fight)
        summary = f"{'Storyteller ' if storyteller else ''}{identity(actor)}: {plain(label, 500)} (sequence {sequence})."
        commit(
            fight,
            before,
            state,
            actor=actor,
            label=label,
            operation_id=operation_id,
            result=result,
            summary=summary,
            sequence=sequence,
        )
        return result


def setup(actor, *, reason="", operation_id=None):
    require(actor, progress=True)
    Fight = _fights()
    room = actor.location
    with transaction.atomic():
        ObjectDB.objects.select_for_update().get(pk=room.pk)
        fight = Fight.objects.filter(room=room, status=Fight.OPEN).first()
        replay = bool(operation_id and fight and fight.entries.filter(operation=operation_id))
        if fight and fight.state.get("participants") and not replay:
            raise CombatError("This room already has a fight. End or shelve it first.")
        if fight is None:
            # A fresh fight. An empty open fight (nobody joined) is reused.
            fight = Fight.objects.create(room=room, state=engine.new_state(), label=plain(reason))
        elif not replay:
            fight.label = plain(reason)
            fight.save(update_fields=["label", "updated_at"])
        ensure_maintenance()

        def operation(state):
            state["imbalance"] = plain(reason)
            return fight.pk

        return execute(
            actor,
            f"set up combat #{fight.pk}. {reason}",
            operation,
            storyteller=True,
            operation_id=operation_id,
            fight=fight,
        )


def quietly(fight, mutate):
    """A small locked write that is not a mechanical transition or journaled.

    It works on stored state (builds as digests) and must not touch builds.
    """
    Fight = _fights()
    with transaction.atomic():
        fight = Fight.objects.select_for_update().get(pk=fight.pk)
        state = validate_state(fight.state)
        result = mutate(state)
        fight.state = state
        fight.save(update_fields=["state", "updated_at"])
        return result


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


def paused_hint(state):
    if state.get("pause_reason") == "reconciliation":
        return "The fight is paused for reconciliation after a staff rollback; staff resume it."
    return "The fight is paused. Once everyone is back, anyone may +combatstory/resume."


def join(actor, side="", *, subject=None, boss=1, turn_limit=None, batch=False, operation_id=None):
    subject = subject or actor
    record = authorize(actor, subject, batch=batch)
    fight = open_fight(actor.location)
    retained = fight.state.get("participants", {}).get(str(subject.pk))
    try:
        build = npc_build(subject, record) if record else snapshot(subject)
    except CombatError:
        if retained is None:
            raise
        build = None  # A rejoin restores this fight's build; the sheet may be mid-edit.
    cap = conf.get("RP_COMBAT_TURN_LIMIT") if turn_limit is None else turn_limit
    name = (
        f"{plain(subject.key)} (NPC, directed by {identity(actor)})"
        if batch and record
        else identity(subject)
    )

    def operation(state):
        if active_elsewhere(subject, fight.pk):
            raise CombatError(
                "That character is active in another fight. Fade there first; "
                "rejoining that fight later restores their place."
            )
        existing = state["participants"].get(str(subject.pk))
        row = engine.join(
            state,
            subject.pk,
            name,
            plain(side, 40),
            build,
            boss=boss,
            turn_limit=cap,
            npc=bool(record),
        )
        row["last_activity"] = time.time()
        state["invitations"].pop(str(subject.pk), None)
        if existing is None:
            if record:
                if batch:
                    row["batch_controller"] = actor.pk
                profile = getattr(record.blueprint, "combat_profile", None)
                if profile:
                    row["policy"] = npc_policy(profile)
        elif build is not None and build.as_dict() != row["build"]:
            notice(
                state,
                f"{row['name']}'s current sheet differs from the build frozen for this fight; "
                "the fight's build is restored. +combat/unlock and /relock adopt the current "
                "sheet if everyone agrees.",
            )
        if state["paused"]:
            notice(state, paused_hint(state))
        return row["id"]

    if retained:
        label = f"{identity(subject)} rejoined, restoring their retained place in this fight"
    else:
        label = (
            f"{identity(subject)} explicitly joined side {plain(side, 40)} with "
            f"{100 * boss} Vitality, personal Turn Limit {cap} and {boss} action(s) per turn"
            + (f" (Boss Mode x{boss})" if boss != 1 else "")
        )
    return execute(actor, label, operation, operation_id=operation_id, subject=subject)


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


def sides(state):
    return sorted({p["side"] for p in state["participants"].values()})


def invite(actor, target, side=""):
    """A private invitation. The invitee chooses any side, or declines."""
    require(actor, progress=True)
    if target.location != actor.location:
        raise CombatError("Invite a character in this room.")
    fight = open_fight(actor.location)

    def mutate(state):
        if str(target.pk) in state["participants"]:
            raise CombatError(f"{identity(target)} is already in this fight.")
        state["invitations"][str(target.pk)] = {
            "by": actor.pk,
            "by_name": identity(actor),
            "side": plain(side, 40),
        }
        return sides(state)

    present = quietly(fight, mutate)
    suggestion = f", suggesting side {plain(side, 40)}" if side else ""
    recipient = owner(target)
    if recipient:
        recipient.msg(
            f"{identity(actor)} invites {identity(target)} to combat{suggestion}. "
            f"Sides so far: {', '.join(present) or 'none yet'}. Use +combat/join <side> to "
            "accept explicitly on any side, or +combat/refuse. No attack has executed."
        )
    return (
        "Invitation sent; the attack has not been declared or paid. Declare again after acceptance."
    )


def refuse(actor):
    """Decline privately: only the inviter is told, and nothing is announced."""
    require(actor)
    fight = open_fight(actor.location)

    def mutate(state):
        invitation = state["invitations"].pop(str(actor.pk), None)
        if invitation is None:
            raise CombatError("You have no pending combat invitation here.")
        return invitation["by"]

    inviter = ObjectDB.objects.filter(pk=quietly(fight, mutate)).first()
    recipient = owner(inviter) if inviter else None
    if recipient:
        recipient.msg(f"{identity(actor)} declined your combat invitation.")
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
    waive=False,
    public=False,
    rng=None,
    operation_id=None,
):
    subject = subject or actor
    authorize(actor, subject)
    state = state_for(actor)
    for target in targets:
        if str(target.pk) not in state["participants"]:
            return invite(actor, target)

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
            waive=waive,
            public=public,
        )
        run_automatic(state, subject.location)
        return ex_id

    return execute(
        actor,
        f"{identity(subject)} declared {plain(key)} against {', '.join(identity(t) for t in targets)}",
        operation,
        operation_id=operation_id,
        subject=subject,
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
        subject=subject,
    )


def run_automatic(state, room):
    """Accept opted-in reactions. Never fails the operation that triggered it.

    A row that could not react by hand is skipped, and a policy choice the
    engine refuses (it validates before spending) stays queued for its owner.
    """
    if state["paused"] or state["ended"]:
        return
    for row in state["participants"].values():
        if (
            not row["auto"]
            or row["status"] != "active"
            or row["hp"] <= 0
            or row.get("return_required")
            or row["correction"]
            or row.get("absent")
        ):
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
            if not partners.modifiers(exchange, row["id"]).auto_resolve:
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
            try:
                engine.reaction(
                    state,
                    row["id"],
                    token,
                    kind,
                    counter=counter if kind == "overpower" else None,
                    domain_effects=conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
                )
            except CombatError:
                continue


def auto_act(actor, *, subject=None, rng=None, operation_id=None):
    subject = subject or actor
    authorize(actor, subject)
    rng = rng or random.SystemRandom()

    def operation(state):
        if engine.participant(state, subject.pk).get("recovering"):
            engine.recover(state, subject.pk)
            return "recovered"
        row = engine.active(state, subject.pk)
        public = []
        for p in state["participants"].values():
            if (
                p["status"] != "active"
                or p["hp"] <= 0
                or p.get("recovering")
                or p["id"] == row["id"]
                or p["correction"]
                or p.get("absent")
            ):
                continue
            # Offer only targets a declaration could reach, so a random pick
            # never fails or sends an ignore prompt the actor did not choose.
            obj = ObjectDB.objects.filter(pk=p["id"]).first()
            if (
                obj is None
                or obj.location != actor.location
                or ignored_by(subject, obj)
                or ignored_by(obj, subject)
            ):
                continue
            public.append(p)
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
        subject=subject,
    )


REQUESTS = {
    "vitality": "vitality",
    "spirit": "spirit",
    "condition": "condition",
    "clearcondition": "clearcondition",
    "requestcap": "cap",
    "requestreturn": "return",
}
STORY_CONDITIONS = {
    "grappled": 10,
    "poisoned": 3,
    "warded": 1,
    "vulnerable": 20,
    "endure": 1,
    "slip_inside": 1,
}


def describe(request):
    value, kind = request["value"], request["kind"]
    text = {
        "vitality": lambda: f"set your Vitality to {value}",
        "spirit": lambda: f"set your Spirit to {value / 100:.2f}",
        "condition": lambda: f"apply {value}",
        "clearcondition": lambda: f"clear {value}",
        "cap": lambda: f"lower your personal Turn Limit to {value}",
        "return": lambda: f"return you to the fight at {value} Vitality",
        "end": lambda: "end the fight",
    }[kind]()
    reason = f" ({request['reason']})" if request.get("reason") else ""
    return f"{request['by_name']} proposes to {text}{reason}"


def end_fight(state, reason):
    if any(p["incoming"] or p["outgoing"] for p in state["participants"].values()):
        raise CombatError("Clear pending exchanges before ending combat.")
    state["ended"] = True
    state["outcome"] = plain(reason) or "Ended by agreement; no narrative outcome imposed"
    state["end_proposal"] = None
    for row in state["participants"].values():
        row["requests"] = [r for r in row["requests"] if r["kind"] != "end"]


def apply_request(state, row, request, *, fight_pk):
    """Apply an accepted storyteller change (or one to a directed NPC)."""
    kind, value = request["kind"], request["value"]
    if kind == "vitality":
        if value > 0 and (
            row["hp"] <= 0 or row.get("return_required") or row["status"] == "withdrawn"
        ):
            raise CombatError("Use requestreturn; the participant must accept their return.")
        row["hp"] = math_clamp(0, row["max_hp"], value)
        if row["hp"] == 0:
            row["return_required"] = True
    elif kind == "spirit":
        row["spirit"] = math_clamp(-1000, 2000, value)
    elif kind == "condition":
        if value not in STORY_CONDITIONS:
            raise CombatError("Choose a supported named condition.")
        # The participant agreed to it, so a Ward does not absorb it.
        engine.condition(row, value, STORY_CONDITIONS[value], 2, wardable=False)
    elif kind == "clearcondition":
        row["conditions"].pop(value, None)
    elif kind == "cap":
        if type(value) is not int or not max(1, row["turns"]) <= value <= row["turn_limit"]:
            raise CombatError(
                "Choose a lower personal Turn Limit within the participant's used/current caps."
            )
        engine.reduce_cap(state, row["id"], value)
    elif kind == "return":
        if state["ended"] or not (
            row["hp"] <= 0 or row.get("return_required") or row["status"] == "withdrawn"
        ):
            raise CombatError(
                "Return applies to an incapacitated or withdrawn participant in an ongoing fight."
            )
        if type(value) is not int or not 1 <= value <= row["max_hp"]:
            raise CombatError("Choose return Vitality from 1 to the participant's maximum.")
        if row["incoming"] or row["outgoing"]:
            raise CombatError("Clear pending exchanges before returning.")
        subject = ObjectDB.objects.filter(pk=row["id"]).first()
        if subject is not None and active_elsewhere(subject, fight_pk):
            raise CombatError("That character is active in another fight. Fade there first.")
        # Restored Vitality is new exposure: returning never erases prior
        # assessment loss or resets personal progress/resources.
        prior_hp = row.get("faded_hp", row["hp"])
        row["exposure"] += value - prior_hp
        row["hp"], row["status"] = value, "active"
        for key in ("faded_hp", "absent", "return_required", "recovering"):
            row.pop(key, None)
    elif kind == "end":
        proposal = state["end_proposal"]
        if not proposal or proposal["id"] != value:
            raise CombatError("That end proposal is no longer open.")
        proposal["pending"] = [key for key in proposal["pending"] if key != row["id"]]
        if not proposal["pending"]:
            end_fight(state, proposal["reason"])
    else:
        raise CombatError("Unknown storyteller request.")


def pending_request(row, argument):
    requests = row["requests"]
    if not requests:
        raise CombatError("You have no pending storyteller requests.")
    if not argument:
        if len(requests) > 1:
            raise CombatError(
                "Several requests are pending; name one: "
                + ", ".join(str(r["id"]) for r in requests)
                + "."
            )
        return requests[0]
    try:
        number = int(str(argument).strip())
    except ValueError:
        raise CombatError("Name a request by its number, as +combat shows it.") from None
    for request in requests:
        if request["id"] == number:
            return request
    raise CombatError("No pending request has that number.")


def pending_revival(state, row, argument):
    offers = [
        token
        for token in row["incoming"]
        if state["exchanges"].get(token.split(":")[0], {}).get("revival")
    ]
    if argument:
        if argument not in offers:
            raise CombatError("No revival offer matches that token.")
        return argument
    if not offers:
        raise CombatError("You have no pending storyteller requests or revival offers.")
    if len(offers) > 1:
        raise CombatError(
            "Several revival offers are pending; name one: " + ", ".join(offers) + "."
        )
    return offers[0]


def withdraw_end_proposal(state):
    state["end_proposal"] = None
    for row in state["participants"].values():
        row["requests"] = [r for r in row["requests"] if r["kind"] != "end"]


def control(
    actor, operation, *, subject=None, argument=None, reason="", rng=None, operation_id=None
):
    subject = subject or actor
    cleanup = operation in ("cancel", "fade", "withdraw", "posed", "decline", "retract", "revive")
    authorize(actor, subject, cleanup=cleanup)
    fight_pk = open_fight(actor.location).pk

    def change(state):
        row = engine.participant(state, subject.pk)
        if operation == "cancel":
            engine.cancel(state, subject.pk, argument)
        elif operation in ("fade", "withdraw"):
            was_paused = state["paused"]
            engine.fade(state, subject.pk, withdraw=operation == "withdraw")
            notice(state, f"{row['name']}'s sheet is released until they rejoin.")
            if state["paused"] and not was_paused:
                notice(state, "Nobody is active, so the fight is paused. " + paused_hint(state))
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
        elif operation in ("accept", "decline") and (
            ":" in str(argument or "") or (not argument and not row["requests"])
        ):
            token = pending_revival(state, row, argument)
            exchange = engine.get_exchange(state, token)
            healer = engine.participant(state, exchange["actor"])["name"]
            if operation == "accept":
                engine.accept_revival(state, subject.pk, token)
                notice(state, f"{row['name']} accepted {healer}'s revival.")
            else:
                engine.cancel(state, subject.pk, token)
                notice(state, f"{row['name']} declined {healer}'s revival and stays down.")
        elif operation == "revive":
            if argument not in ("accept", "ask"):
                raise CombatError("Choose +combat/revive accept or ask.")
            row["revive"] = argument
        elif operation == "retract":
            engine.retract(state, subject.pk)
            notice(state, f"{row['name']} withdrew an unaccepted revival offer.")
        elif operation == "recover":
            engine.recover(state, subject.pk)
            notice(state, f"{row['name']} takes their recovery action and is back in the fight.")
        elif operation in ("accept", "decline"):
            request = pending_request(row, argument)
            row["requests"].remove(request)
            if operation == "accept":
                apply_request(state, row, request, fight_pk=fight_pk)
                notice(
                    state, f"{row['name']} accepted request {request['id']}: {describe(request)}."
                )
            else:
                if request["kind"] == "end":
                    withdraw_end_proposal(state)
                notice(
                    state, f"{row['name']} declined request {request['id']}: {describe(request)}."
                )
        else:
            raise CombatError("Unknown combat control.")
        return operation

    return execute(
        actor,
        f"{identity(subject)} used {plain(operation)} {plain(argument or '')}. {plain(reason)}",
        change,
        progressing=not cleanup,
        operation_id=operation_id,
        subject=subject,
    )


def propose_end(state, actor, reason):
    """Ending needs every present, active player character's agreement."""
    if any(p["incoming"] or p["outgoing"] for p in state["participants"].values()):
        raise CombatError("Clear pending exchanges before ending combat.")
    if state["end_proposal"]:
        raise CombatError("An end proposal is already waiting for answers.")
    voters = [
        p
        for p in state["participants"].values()
        if not p["npc"]
        and p["status"] == "active"
        and not p.get("absent")
        and p["id"] != str(actor.pk)
    ]
    if not voters:
        end_fight(state, reason)
        return
    number = state["next_request"]
    state["next_request"] += 1
    state["end_proposal"] = {
        "id": number,
        "pending": [p["id"] for p in voters],
        "reason": plain(reason),
    }
    for p in voters:
        p["requests"].append(
            {
                "id": number,
                "kind": "end",
                "value": number,
                "by": actor.pk,
                "by_name": identity(actor),
                "reason": plain(reason),
            }
        )
    notice(
        state,
        f"Ending needs agreement from {', '.join(p['name'] for p in voters)}: "
        f"+combat/accept {number} or /decline {number}.",
    )


def storyteller(actor, operation, *, target=None, value=None, reason="", operation_id=None):
    """Open to everyone and publicly attributed. Changes to another player's
    character wait for that player's acceptance; NPCs you may direct change
    immediately; ending needs the present players' agreement."""
    if operation == "boss":
        raise CombatError(
            "Set Boss Mode when joining; live reconfiguration and Boss Checks are not in 0.1."
        )
    if operation == "shelve":
        return shelve(actor, reason, operation_id=operation_id)
    is_staff = staff(actor)
    fight_pk = open_fight(actor.location).pk

    def change(state):
        row = engine.participant(state, target.pk) if target else None
        if operation == "pause":
            if not state["paused"]:
                state["paused"], state["pause_reason"] = True, "storyteller"
        elif operation == "resume":
            if not state["paused"]:
                raise CombatError("This fight is not paused.")
            if state.get("pause_reason") == "reconciliation" and not is_staff:
                raise CombatError(paused_hint(state))
            state["paused"], state["pause_reason"] = False, ""
            run_automatic(state, actor.location)
        elif operation == "end":
            propose_end(state, actor, reason)
        elif operation == "imbalance":
            state["imbalance"] = plain(reason)
        elif operation in REQUESTS and row:
            request = {
                "kind": REQUESTS[operation],
                "value": value,
                "by": actor.pk,
                "by_name": identity(actor),
                "reason": plain(reason),
            }
            if row["npc"]:
                authorize(actor, target, batch=True)
                apply_request(state, row, request, fight_pk=fight_pk)
            else:
                # Validate now, so a request that could never apply is refused.
                trial = clone(state)
                apply_request(trial, trial["participants"][row["id"]], request, fight_pk=fight_pk)
                request["id"] = state["next_request"]
                state["next_request"] += 1
                row["requests"].append(request)
                notice(
                    state,
                    f"{row['name']} may +combat/accept {request['id']} or /decline {request['id']}.",
                )
        else:
            raise CombatError("Unknown storyteller operation or missing target.")
        return operation

    return execute(
        actor,
        f"{operation} {identity(target) if target else ''} {plain(value if value is not None else '')}. {plain(reason)}",
        change,
        progressing=operation not in ("pause", "end"),
        storyteller=True,
        operation_id=operation_id,
    )


def math_clamp(low, high, value):
    if type(value) is not int:
        raise CombatError("Supply a whole resource value.")
    return max(low, min(high, value))


def release_pending(state, row):
    """Cancel only what has not executed for this participant.

    Unaccepted incoming packets and unaccepted targets of its own outgoing
    exchange are canceled with refunds, and an open Burst is closed. An
    accepted reaction stays committed until its peers answer.
    """
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
                if target not in exchange["reactions"] and target not in exchange["canceled"]:
                    engine.cancel(state, target, token)


def shelve_state(state):
    for row in state["participants"].values():
        release_pending(state, row)
    for row in state["participants"].values():
        if row["status"] == "active":
            engine.fade(state, row["id"])
            row.pop("absent", None)
    state["paused"], state["pause_reason"] = True, "faded"
    state["end_proposal"] = None
    for row in state["participants"].values():
        row["requests"] = [r for r in row["requests"] if r["kind"] != "end"]


def shelve(actor, reason="", *, operation_id=None):
    """Set a fight aside: everyone Fades with their place retained, sheets
    unlock, and the room is free. Nothing executed is undone."""
    Fight = _fights()

    def change(state):
        if state["ended"]:
            raise CombatError("This fight has ended.")
        shelve_state(state)
        notice(
            state,
            "Unaccepted packets were canceled with refunds. Anyone in it can later "
            "+combatstory/unshelve this fight and each participant rejoins with +combat/join.",
        )
        return "shelved"

    fight = open_fight(actor.location)
    with transaction.atomic():
        result = execute(
            actor,
            f"shelved fight #{fight.pk}. {plain(reason)}",
            change,
            progressing=False,
            storyteller=True,
            operation_id=operation_id,
            fight=fight,
            close=Fight.SHELVED,
        )
        if plain(reason).strip():
            # The reason names the fight in +combatstory/shelved listings.
            Fight.objects.filter(pk=fight.pk).update(label=plain(reason))
        return result


def visible_shelved(actor):
    """Shelved fights the actor took part in, or that were set aside here."""
    Fight = _fights()
    return [
        fight
        for fight in Fight.objects.filter(status=Fight.SHELVED).order_by("-updated_at")
        if str(actor.pk) in fight.state.get("participants", {})
        or fight.room_id == getattr(actor.location, "pk", None)
    ]


def shelved(actor):
    require(actor)
    lines = [
        f"#{fight.pk}: {plain(fight.label) or 'untitled'}; "
        + ", ".join(p["name"] for p in fight.state.get("participants", {}).values())
        + f"; shelved {fight.closed_at:%Y-%m-%d}."
        for fight in visible_shelved(actor)[:20]
    ]
    return "\n".join(lines) or "No shelved fights involve you or this room."


def unshelve(actor, number, *, operation_id=None):
    require(actor, progress=True)
    Fight = _fights()
    room = actor.location
    with transaction.atomic():
        ObjectDB.objects.select_for_update().get(pk=room.pk)
        if Fight.objects.filter(room=room, status=Fight.OPEN).exists():
            raise CombatError("This room already has a fight. End or shelve it first.")
        fight = next((f for f in visible_shelved(actor) if f.pk == number), None)
        if fight is None:
            raise CombatError("No shelved fight with that number involves you or this room.")
        fight = Fight.objects.select_for_update().get(pk=fight.pk)
        fight.status, fight.room, fight.closed_at = Fight.OPEN, room, None
        fight.save()
        ensure_maintenance()

        def operation(state):
            notice(state, "Each participant rejoins with +combat/join. " + paused_hint(state))
            return fight.pk

        return execute(
            actor,
            f"brought shelved fight #{fight.pk} here",
            operation,
            storyteller=True,
            operation_id=operation_id,
            fight=fight,
        )


def rollback(actor, sequence, reason):
    require(actor)
    if not staff(actor):
        raise CombatError("Only staff may roll back accepted or resolved combat.")
    if not plain(reason).strip():
        raise CombatError("Staff rollback requires a visible reason.")
    Fight = _fights()
    fight = current_fight(actor.location)
    with transaction.atomic():
        fight = Fight.objects.select_for_update().get(pk=fight.pk)
        if fight.status == Fight.ENDED and Fight.objects.filter(
            room=actor.location, status=Fight.OPEN
        ).exclude(pk=fight.pk):
            raise CombatError("Another fight is open here; end or shelve it before rolling back.")
        checkpoint = fight.entries.filter(sequence=sequence, superseded=False).first()
        if checkpoint is None or checkpoint.before is None:
            raise CombatError("Choose a retained, unsuperseded sequence.")
        current = load(fight)
        restored = hydrate(fight, clone(checkpoint.before))
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
            if row["status"] != "active":
                continue  # Faded rows restore their own frozen build on rejoin.
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
            restored["paused"], restored["pause_reason"] = True, "reconciliation"
        fight.entries.filter(sequence__gte=sequence).update(superseded=True)
        fight.status, fight.closed_at = Fight.OPEN, None
        summary = (
            f"Staff {identity(actor)} rolled the whole fight back before sequence {sequence}: "
            f"{plain(reason)}. Pending tokens changed."
        )
        if reconciliation:
            summary += (
                " Fight paused: reconcile external build changes/deletions for "
                + ", ".join(reconciliation)
                + "."
            )
        removed = [key for key in current["participants"] if key not in restored["participants"]]
        commit(
            fight,
            current,
            restored,
            actor=actor,
            label=summary,
            operation_id=str(uuid.uuid4()),
            result="rollback",
            summary=summary,
            sequence=next_sequence(fight),
            announce_exchanges=False,
            release=removed,
        )


def journal(actor, *, limit=40):
    require(actor)
    fight = current_fight(actor.location)
    entries = list(fight.entries.order_by("-sequence")[:limit])[::-1]
    lines = [
        f"{entry.sequence}: {'superseded; ' if entry.superseded else ''}{entry.summary}"
        for entry in entries
    ]
    return "\n".join(lines) or "No recorded transitions."


def read(actor, token, domain, *, subject=None, operation_id=None):
    subject = subject or actor
    authorize(actor, subject)

    def operation(state):
        exchange = engine.get_exchange(state, token)
        attacker = ObjectDB.objects.filter(pk=exchange["actor"]).first()
        if attacker is None:
            raise CombatError("The attacker has left; cancel the unaccepted incoming attack.")
        interaction(subject, attacker)
        bet = engine.read_bet(
            state, subject.pk, token, domain, conf.get("RP_COMBAT_DOMAIN_EFFECTS")
        )
        if bet is None:
            return (
                f"Incoming {token}: the attacker resisted your Read. No reaction has been accepted."
            )
        return f"Incoming {token}: RPS {bet or 'none'}. No reaction has been accepted."

    return execute(
        actor,
        f"{identity(subject)} used Read on {plain(token)}",
        operation,
        operation_id=operation_id,
        subject=subject,
    )


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
    if exchange.get("public_bet"):
        fallbacks.append(f"Calling the shot: a {exchange['bet']} bet, made public")
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
                + (" Domain effect resisted." if outcome.get("domain_resisted") else "")
            )
        else:
            lines.append(
                f"{target['name']}: Spirit change {outcome['spirit'] / 100:+.2f}; healed {outcome['healing']} Vitality."
                + (" Domain effect resisted." if outcome.get("domain_resisted") else "")
                + (
                    ""
                    if "revived" not in outcome
                    else " Revived, with no recovery action (Medicine)."
                    if outcome.get("recovery_waived")
                    else " Revived; one recovery action follows."
                    if outcome["revived"]
                    else " The Heal restored nothing, so they stay down."
                )
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
    if state["paused"] and not state["ended"]:
        lines.append(paused_hint(state))
    for row in state["participants"].values():
        lines.append(
            f"{row['name']} [{row['side']}]: {row['hp']}/{row['max_hp']} Vitality; "
            f"turns {row['turns']}/{row['turn_limit']}, allowance {row['actions_left']}; {row['status']}; "
            f"{'acted' if row['clock'] else 'has not acted'}; incoming {len(row['incoming'])}."
        )
    key = str((subject or actor).pk)
    own = state["participants"].get(key)
    invitation = state.get("invitations", {}).get(key)
    if invitation and not own:
        suggestion = f", suggesting side {invitation['side']}" if invitation["side"] else ""
        lines.append(
            f"Invitation from {invitation['by_name']}{suggestion}. Sides: "
            f"{', '.join(sides(state)) or 'none yet'}. +combat/join <side> or +combat/refuse."
        )
    if own:
        if subject and subject != actor:
            authorize(actor, subject, cleanup=True)
        lines.append(
            f"Your resources: Reserves {own['reserves']}/5; Spirit {own['spirit'] / 100:.2f}; "
            f"Transcendence {own['transcendence']}/100; Resist pressure {own['pressure']}/30; "
            f"Auto-Resolve {'on' if own['auto'] else 'off'}; pose {'owed' if own['pose'] else 'clear'}; "
            f"build {'unlocked for correction' if own['correction'] else 'frozen'}; "
            f"revival from allies: {'accepted automatically' if own.get('revive') == 'accept' else 'ask me'}."
        )
        if own.get("recovering"):
            lines.append(
                "You are recovering: +combat/recover spends one action and returns you to the fight."
                if own["turns"] < own["turn_limit"]
                else "You were revived, but your personal Turn Limit is used up: you cannot recover or act again in this fight."
            )
        for request in own["requests"]:
            lines.append(
                f"Request {request['id']}: {describe(request)}. "
                f"+combat/accept {request['id']} or /decline {request['id']}."
            )
        for information in own.get("information", {}).values():
            traits = ", ".join(f"{key}: {tag}" for key, tag in information["traits"]) or "none"
            flaws = ", ".join(f"{key}: {tag}" for key, tag in information["flaws"]) or "none"
            lines.append(
                f"Analyzed {information['name']}: resistance/vulnerability {traits}; combat Flaws {flaws}."
            )
        for token in own["incoming"]:
            exchange = engine.get_exchange(state, token)
            if exchange.get("revival"):
                healer = engine.participant(state, exchange["actor"])["name"]
                after = (
                    "you return at once, with no recovery action (Medicine)"
                    if exchange["waive_recovery"]
                    else "you take one recovery action before acting again"
                    if own["turns"] < own["turn_limit"]
                    else "your Turn Limit is used up, so you won't act again in this fight"
                )
                lines.append(
                    f"Revival offer {token} from {healer}: if the Heal restores Vitality, {after}. "
                    f"+combat/accept {token} or /decline {token}."
                )
                continue
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
    lines.extend(plain(line, 500) for line in partners.lines(state, key))
    return "\n".join(lines)


def help_for(actor):
    require(actor)
    fight = _fights().objects.filter(room=actor.location, status="open").first()
    state = load(fight) if fight else engine.new_state()
    return "\n".join(
        [
            "Use help +combat for core commands.",
            *(plain(line, 500) for line in partners.lines(state, actor.pk, help=True)),
        ]
    )


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
        f"Incoming {plain(token)}: "
        + (
            f"the attacker called a {view.public_bet} bet publicly; "
            if view.public_bet
            else "neutral RPS estimates; "
        )
        + "unseen offensive scores use a neutral damage estimate."
    ]
    for reaction in view.reactions:
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
            rps=view.public_bet,
            rps_shift=tuple(Fraction(v) for v in view.public_shift),
            damage_boost=Fraction(view.damage_boost),
            surge=Fraction(view.surge),
        )
        lines.append(
            f"{reaction.title()}: {result.chance}% success; successful incoming damage estimate {result.damage}. "
            + ("Standard balanced counter." if reaction == "overpower" else "")
        )
    return "\n".join(lines)
