# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authorization and atomic NPC operations; commands are thin clients."""

import json
from datetime import timedelta

from django.apps import apps
from django.db import IntegrityError, transaction
from django.utils import timezone
from evennia.locks.lockhandler import check_lockstring
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object

from evennia_links.runtime import get as runtime
from evennia_rp_rules.ruleset import get_ruleset

from . import conf
from .models import (
    NPCBlueprint,
    NPCCombatProfile,
    NPCPermission,
    NPCPermissionRequest,
    NPCSpawnRecord,
    PlotNPCLink,
)


class NPCError(ValueError):
    """A refusal safe to show the caller."""


def is_staff(actor):
    return bool(actor and check_lockstring(actor, conf.get("NPCS_STAFF_LOCK")))


def require(actor, *, write=False, cleanup=False):
    from evennia.objects.objects import DefaultCharacter

    if (
        not isinstance(actor, DefaultCharacter)
        or not actor.pk
        or actor.tags.has("npc", category="npc_system")
    ):
        raise NPCError("Use your own character to manage NPCs.")
    if cleanup:
        return
    if not runtime("NPCS_REVEALED") and not is_staff(actor):
        raise NPCError("NPCs are not available yet.")
    if write and runtime("NPCS_FROZEN"):
        raise NPCError("NPC activity is paused. You can still release or despawn an NPC.")


def text(value, *, maximum=200, empty=False):
    if not isinstance(value, str):
        raise NPCError("Expected text.")
    value = value.strip()
    if (not value and not empty) or len(value) > maximum or any(not c.isprintable() for c in value):
        raise NPCError(f"Use printable text of at most {maximum} characters.")
    if any(c in value for c in "|<>"):
        raise NPCError("Use plain text without formatting or markup.")
    return value


def find_blueprint(ref):
    value = str(ref).strip().lstrip("#")
    query = NPCBlueprint.objects
    query = query.filter(pk=int(value)) if value.isdecimal() else query.filter(name__iexact=value)
    result = query.first()
    if result is None:
        raise NPCError("No NPC blueprint matches that name or id.")
    return result


def can_manage(actor, blueprint):
    return is_staff(actor) or blueprint.permissions.filter(holder=actor, level="owner").exists()


def can_play(actor, blueprint):
    return not blueprint.archived and (
        blueprint.kind == "template"
        or is_staff(actor)
        or blueprint.permissions.filter(holder=actor).exists()
    )


def _locked(actor, blueprint, *, manage=False, cleanup=False):
    require(actor, write=True, cleanup=cleanup)
    blueprint = NPCBlueprint.objects.select_for_update().get(pk=blueprint.pk)
    allowed = can_manage(actor, blueprint) if manage else can_play(actor, blueprint)
    if not allowed:
        raise NPCError(
            "You do not have permission to manage this NPC."
            if manage
            else "You do not have permission to play this NPC."
        )
    return blueprint


def validate_stats(value):
    if not isinstance(value, dict) or len(value) > 100:
        raise NPCError("Stats must be a mapping of stat keys to ratings.")
    ruleset = get_ruleset()
    cleaned = {}
    for key, rating in value.items():
        stat = ruleset.stats.get(key)
        if stat is None or not isinstance(rating, str):
            raise NPCError(f"Unknown stat or invalid rating: {key}.")
        try:
            stat.scale.parse(rating)
        except (ValueError, KeyError) as exc:
            raise NPCError(f"Invalid rating for {key}: {rating}.") from exc
        cleaned[key] = rating.strip()
    return cleaned


def validate_abilities(value):
    if not isinstance(value, list) or len(value) > 100:
        raise NPCError("Abilities must be a list of at most 100 stable identifiers.")
    return list(dict.fromkeys(text(item, maximum=100) for item in value))


def create_blueprint(
    actor, name, kind="unique", *, description="", stat_block=None, abilities=None
):
    require(actor, write=True)
    name = text(name)
    if kind not in NPCBlueprint.Kind.values:
        raise NPCError("Choose template or unique.")
    stats = validate_stats(stat_block or {})
    abilities = validate_abilities(abilities or [])
    try:
        with transaction.atomic():
            # Serialize creation on the actor as well as checking case-folded
            # names. The DB unique constraint catches identical-name races.
            ObjectDB.objects.select_for_update().get(pk=actor.pk)
            if NPCBlueprint.objects.filter(name__iexact=name).exists():
                raise NPCError("An NPC already has that name.")
            blueprint = NPCBlueprint.objects.create(
                name=name,
                kind=kind,
                creator=actor,
                creator_name=actor.key[:200],
                description=text(description, maximum=10000, empty=True),
                stat_block=stats,
                abilities=abilities,
            )
            # Templates are intrinsically open. A nullable owner never turns
            # into an open permission when a character is deleted.
            NPCPermission.objects.create(
                blueprint=blueprint, holder=actor, holder_name=actor.key[:200], level="owner"
            )
            NPCCombatProfile.objects.create(blueprint=blueprint)
            return blueprint
    except IntegrityError as exc:
        raise NPCError("That NPC name is already in use; choose another.") from exc


def edit_blueprint(actor, blueprint, **changes):
    validators = {
        "description": lambda value: text(value, maximum=10000, empty=True),
        "short_desc": lambda value: text(value, empty=True),
        "stat_block": validate_stats,
        "abilities": validate_abilities,
    }
    if not changes or set(changes) - validators.keys():
        raise NPCError("Edit description, short_desc, stat_block or abilities.")
    cleaned = {key: validators[key](value) for key, value in changes.items()}
    with transaction.atomic():
        blueprint = _locked(actor, blueprint, manage=True)
        for key, value in cleaned.items():
            setattr(blueprint, key, value)
        blueprint.save(update_fields=[*cleaned, "updated_at"])
        # Descriptions update spawned objects; stats are read from the durable
        # blueprint so there is no stale copy to synchronize.
        if "description" in cleaned:
            for spawn in blueprint.spawns.filter(despawned_at=None, spawned_object__isnull=False):
                spawn.spawned_object.db.desc = blueprint.description
        return blueprint


def permit(actor, blueprint, holder, *, revoke=False):
    require(holder, cleanup=True)
    with transaction.atomic():
        blueprint = _locked(actor, blueprint, manage=True)
        if blueprint.permissions.filter(holder=holder, level="owner").exists():
            raise NPCError("Transfer ownership before revoking the owner.")
        if revoke:
            blueprint.permissions.filter(holder=holder, level="player").delete()
            for spawn in blueprint.spawns.filter(controller=holder):
                _release(spawn)
        else:
            blueprint.permissions.update_or_create(
                holder=holder, defaults={"holder_name": holder.key[:200], "level": "player"}
            )


def transfer(actor, blueprint, holder):
    require(holder, cleanup=True)
    with transaction.atomic():
        blueprint = _locked(actor, blueprint, manage=True)
        blueprint.permissions.filter(level="owner").update(level="player")
        blueprint.permissions.update_or_create(
            holder=holder,
            defaults={
                "holder_name": holder.key[:200],
                "level": "owner",
                "last_played": timezone.now(),
            },
        )


def request_permission(actor, blueprint, reason=""):
    require(actor, write=True)
    reason = text(reason, maximum=2000, empty=True)
    with transaction.atomic():
        blueprint = NPCBlueprint.objects.select_for_update().get(pk=blueprint.pk)
        if blueprint.archived:
            raise NPCError("This NPC is archived.")
        if can_play(actor, blueprint):
            raise NPCError("You already have permission to play this NPC.")
        if blueprint.requests.filter(requester=actor, status="pending").exists():
            raise NPCError("You already have a pending request.")
        request = NPCPermissionRequest.objects.create(
            blueprint=blueprint, requester=actor, requester_name=actor.key[:200], reason=reason
        )
        owners = list(blueprint.permissions.filter(level="owner"))
        days = conf.get("NPCS_IDLE_OWNER_DAYS")
        # Only a sole, still-existing owner qualifies. Deletion or ambiguity
        # requires explicit staff recovery, never silent ownership takeover.
        if days is not None and len(owners) == 1 and owners[0].holder_id:
            owner = owners[0]
            since = owner.last_played or owner.granted_at
            if since <= timezone.now() - timedelta(days=days):
                _resolve_request(request, approved=True, automatic=True)
        recipients = [actor, *[owner.holder for owner in owners if owner.holder_id]]
        transaction.on_commit(
            lambda: _notify(
                recipients,
                f"NPC permission request #{request.pk} for {blueprint.name}: {request.status}.",
            )
        )
        return request


def _resolve_request(request, *, approved, automatic=False):
    if approved:
        if request.requester_id is None:
            raise NPCError("The requester no longer exists.")
        NPCPermission.objects.get_or_create(
            blueprint=request.blueprint,
            holder=request.requester,
            defaults={"holder_name": request.requester_name, "level": "player"},
        )
    request.status = "auto_approved" if automatic else "approved" if approved else "denied"
    request.resolved_at = timezone.now()
    request.save(update_fields=["status", "resolved_at"])


def resolve_request(actor, ref, *, approved):
    with transaction.atomic():
        try:
            request = NPCPermissionRequest.objects.get(pk=int(str(ref).lstrip("#")))
        except (ValueError, NPCPermissionRequest.DoesNotExist) as exc:
            raise NPCError("No permission request matches that id.") from exc
        _locked(actor, request.blueprint, manage=True)
        request.refresh_from_db()
        if request.status != "pending":
            raise NPCError("This request is already resolved.")
        _resolve_request(request, approved=approved)
        transaction.on_commit(
            lambda: _notify([request.requester], f"NPC request #{request.pk}: {request.status}.")
        )
        return request


def _notify(characters, message):
    from evennia.utils import logger

    for character in characters:
        if character is not None:
            try:
                character.msg(message)
            except Exception:
                logger.log_trace("NPC notification failed")


def spawn(actor, blueprint):
    try:
        with transaction.atomic():
            blueprint = _locked(actor, blueprint)
            # Read actual persisted location instead of trusting a stale caller.
            fresh_actor = ObjectDB.objects.select_for_update().get(pk=actor.pk)
            room = fresh_actor.location
            if room is None:
                raise NPCError("You need a room to spawn an NPC.")
            if blueprint.kind == "unique" and blueprint.spawns.filter(despawned_at=None).exists():
                raise NPCError("That unique NPC is already spawned.")
            npc = create_object(
                conf.get("NPCS_TYPECLASS"), key=blueprint.name, location=room, home=room
            )
            from .typeclasses import NPCCharacterMixin

            if not isinstance(npc, NPCCharacterMixin):
                raise NPCError("NPCS_TYPECLASS must include NPCCharacterMixin first.")
            npc.db.desc = blueprint.description
            record = NPCSpawnRecord.objects.create(
                blueprint=blueprint,
                spawned_object=npc,
                spawned_object_name=npc.key,
                spawner=actor,
                spawner_name=actor.key[:200],
                room_id_snapshot=room.pk,
                last_active_at=timezone.now(),
                unique_blueprint=blueprint if blueprint.kind == "unique" else None,
            )
            blueprint.permissions.filter(holder=actor).update(last_played=timezone.now())
            return record
    except IntegrityError as exc:
        raise NPCError("That unique NPC is already spawned; refresh and try again.") from exc


def record_for(npc):
    return (
        NPCSpawnRecord.objects.select_related("blueprint", "controller")
        .filter(spawned_object=npc, despawned_at=None)
        .first()
    )


def find_spawn(actor, ref, *, cleanup=False):
    require(actor, cleanup=cleanup)
    value = str(ref).strip().lstrip("#")
    query = NPCSpawnRecord.objects.filter(despawned_at=None, spawned_object__isnull=False)
    query = (
        query.filter(spawned_object_id=int(value))
        if value.isdecimal()
        else query.filter(spawned_object_name__iexact=value)
    )
    if not is_staff(actor):
        query = query.filter(spawned_object__db_location_id=getattr(actor.location, "pk", None))
    matches = list(query[:2])
    if len(matches) != 1:
        raise NPCError("Choose one spawned NPC by its object #id in this room.")
    return matches[0]


def control(actor, record):
    with transaction.atomic():
        _locked(actor, record.blueprint)
        ObjectDB.objects.select_for_update().get(pk=actor.pk)
        record = (
            NPCSpawnRecord.objects.select_for_update()
            .select_related("spawned_object")
            .get(pk=record.pk)
        )
        npc = record.spawned_object
        if record.despawned_at or npc is None or npc.location != actor.location:
            raise NPCError("The NPC must be active in your room.")
        if record.controller_id and record.controller_id != actor.pk:
            raise NPCError("Someone is already playing this NPC.")
        if npc.account:
            raise NPCError("This NPC is fully puppeted; its player must return first.")
        for old in NPCSpawnRecord.objects.filter(controller=actor).exclude(pk=record.pk):
            _release(old)
        record.controller = actor
        record.controller_name = actor.key[:200]
        record.last_active_at = timezone.now()
        record.save(update_fields=["controller", "controller_name", "last_active_at"])
        record.blueprint.permissions.filter(holder=actor).update(last_played=timezone.now())
        return npc


def controlled(actor):
    """Revalidate every action, including after movement, revocation or reload."""
    if actor.tags.has("npc", category="npc_system"):
        record = record_for(actor)
        if not record or not record.controller:
            raise NPCError("This NPC is no longer controlled. Use +npc/unfullpuppet.")
        player = record.controller
        require(player, write=True)
        if not can_play(player, record.blueprint):
            raise NPCError("Your permission to play this NPC has ended.")
        return actor, player
    record = (
        NPCSpawnRecord.objects.select_related("spawned_object", "blueprint")
        .filter(controller=actor, despawned_at=None)
        .first()
    )
    if record is None:
        return None, actor
    require(actor, write=True)
    npc = record.spawned_object
    if npc is None or npc.location != actor.location or not can_play(actor, record.blueprint):
        release(actor)
        raise NPCError("NPC portrayal ended: location or permission changed.")
    return npc, actor


def attribution(npc):
    from evennia.utils.ansi import strip_ansi

    def label(value):
        value = strip_ansi(value).replace("<", "").replace(">", "")
        value = "".join(c for c in value if c.isprintable())
        return value if len(value) <= 100 else value[:97] + "..."

    record = record_for(npc)
    if record and record.controller_id:
        return f"{label(npc.key)} (NPC, played by {label(record.controller_name)})"
    return f"{label(npc.key)} (NPC)"


def portray(actor, body, *, pose_type="pose"):
    npc, player = controlled(actor)
    if npc is None:
        raise NPCError("Choose an NPC with +npc/puppet first.")
    body = text(body, maximum=10000)
    name = attribution(npc)
    rendered = (
        f'{name} says, "{body}"'
        if pose_type == "say"
        else f"{name}: {body}"
        if pose_type == "emit"
        else f"{name}{'' if pose_type == 'semipose' else ' '}{body}"
    )
    if npc.location is None:
        raise NPCError("The NPC has no location.")
    from .integrations import require_scene_access

    require_scene_access(npc, player)
    note_activity(npc, player)
    npc.location.msg_contents(
        text=("{npc_text}", {"type": "pose"}), mapping={"npc_text": rendered}, from_obj=npc
    )
    # NPCs use their own signal, so host PC activity hooks cannot accidentally
    # award RP XP or lock/spend a chargen build for virtual portrayal.
    from .signals import npc_pose_recorded

    npc.attributes.add("last_pose_time", timezone.now().timestamp())
    npc.attributes.add("last_pose_text", rendered)
    npc_pose_recorded.send_robust(
        sender=type(npc),
        npc=npc,
        actor=player,
        text=rendered,
        pose_type="pose" if pose_type == "semipose" else pose_type,
    )
    return rendered


def note_activity(npc, actor):
    now = timezone.now()
    record = record_for(npc)
    if record:
        NPCSpawnRecord.objects.filter(pk=record.pk).update(last_active_at=now)
        record.blueprint.permissions.filter(holder=actor).update(last_played=now)


def _release(record):
    npc, player = record.spawned_object, record.controller
    if npc is not None and npc.account:
        account = npc.account
        for session in list(npc.sessions.all()):
            account.unpuppet_object(session)
            if player and player.access(account, "puppet"):
                account.puppet_object(session, player)
    record.controller = None
    record.controller_name = ""
    record.save(update_fields=["controller", "controller_name"])


def release(actor):
    require(actor, cleanup=True)
    for record in NPCSpawnRecord.objects.filter(controller=actor):
        _release(record)


def release_npc(npc):
    # at_post_unpuppet must not recurse through _release.
    NPCSpawnRecord.objects.filter(spawned_object=npc).update(controller=None, controller_name="")


def despawn(actor, record):
    with transaction.atomic():
        require(actor, cleanup=True)
        NPCBlueprint.objects.select_for_update().get(pk=record.blueprint_id)
        record = NPCSpawnRecord.objects.select_for_update().get(pk=record.pk)
        if actor.pk not in (record.spawner_id, record.controller_id) and not can_manage(
            actor, record.blueprint
        ):
            raise NPCError("Only the spawner, controller, owner or staff may despawn this NPC.")
        _despawn(record)


def _despawn(record):
    if record.despawned_at:
        return
    _release(record)
    npc = record.spawned_object
    record.despawned_at = timezone.now()
    record.unique_blueprint = None
    record.save(update_fields=["despawned_at", "unique_blueprint"])
    if npc is not None and npc.delete() is False:
        raise NPCError("The host refused to delete this NPC.")


def archive(actor, blueprint, *, archived=True):
    with transaction.atomic():
        blueprint = _locked(actor, blueprint, manage=True)
        for record in blueprint.spawns.filter(despawned_at=None):
            _despawn(record)
        blueprint.archived = archived
        blueprint.save(update_fields=["archived", "updated_at"])


def maintain():
    """Periodic fallback; last NPC or live spawner activity keeps a spawn alive."""
    seconds = conf.get("NPCS_SPAWN_IDLE_SECONDS")
    cutoff = timezone.now() - timedelta(seconds=seconds) if seconds else None
    count = 0
    for candidate in NPCSpawnRecord.objects.filter(despawned_at=None).select_related(
        "spawner", "spawned_object"
    ):
        with transaction.atomic():
            NPCBlueprint.objects.select_for_update().get(pk=candidate.blueprint_id)
            record = NPCSpawnRecord.objects.select_for_update().get(pk=candidate.pk)
            if record.despawned_at:
                continue
            sessions = []
            for character in (record.spawner, record.spawned_object):
                if character is not None:
                    sessions.extend(character.sessions.all())
            timestamps = [getattr(session, "cmd_last_visible", 0) for session in sessions]
            if timestamps and max(timestamps) > record.last_active_at.timestamp():
                record.last_active_at = timezone.datetime.fromtimestamp(
                    max(timestamps), tz=timezone.get_current_timezone()
                )
                record.save(update_fields=["last_active_at"])
            if record.spawned_object_id is None or (cutoff and record.last_active_at < cutoff):
                _despawn(record)
                count += 1
    return count


def full_puppet(actor, record, session):
    if not conf.get("NPCS_ALLOW_FULL_PUPPET"):
        raise NPCError("Full puppeting is disabled; use +npc/puppet.")
    account = actor.account
    if not account or not session or session.get_account() != account or session.puppet != actor:
        raise NPCError("Full puppeting requires your active character session.")
    npc = control(actor, record)
    original_room = actor.location
    npc.ndb.npc_puppet_token = (account.pk, session.sessid, actor.pk)
    try:
        account.puppet_object(session, npc)
        if session.puppet != npc:
            raise NPCError("The account could not switch to the NPC.")
        # The player's dormant character remains visible. Ordinary Evennia
        # unpuppeting stashes PCs off-grid; this is an intentional cameo switch.
        actor.location = original_room
    except Exception:
        release(actor)
        if session.puppet != actor and actor.access(account, "puppet"):
            account.puppet_object(session, actor)
        raise
    finally:
        npc.ndb.npc_puppet_token = None
    return npc


def consume_full_puppet_token(npc, account, session):
    token = npc.ndb.npc_puppet_token
    npc.ndb.npc_puppet_token = None
    if not token or session is None or token[:2] != (account.pk, session.sessid):
        return False
    record = record_for(npc)
    if not record or record.controller_id != token[2]:
        return False
    require(record.controller, write=True)
    return can_play(record.controller, record.blueprint)


def return_from_full(npc, session):
    record = record_for(npc)
    if not record or not npc.account or session not in npc.sessions.all():
        raise NPCError("You are not fully puppeting this NPC.")
    _release(record)


def edit_profile(actor, blueprint, data):
    require(actor, write=True)
    if not runtime("NPCS_COMBAT_PROFILES_REVEALED"):
        raise NPCError("NPC combat profiles are not available yet.")
    keys = {
        "target_policy",
        "action_weights",
        "special_moves",
        "reaction_policy",
        "boss_check_schedule",
    }
    if (
        not isinstance(data, dict)
        or not data
        or data.keys() - keys
        or len(json.dumps(data)) > 20000
    ):
        raise NPCError("Use a combat profile mapping with documented keys.")
    if "target_policy" in data:
        data["target_policy"] = text(data["target_policy"], maximum=100)
    if "action_weights" in data:
        weights = data["action_weights"]
        if (
            not isinstance(weights, dict)
            or any(
                not isinstance(k, str) or type(v) is not int or v < 0 for k, v in weights.items()
            )
            or (weights and not any(weights.values()))
        ):
            raise NPCError("Action weights must be nonnegative integers, with a positive total.")
        data["action_weights"] = {text(k, maximum=100): v for k, v in weights.items()}
    if "special_moves" in data:
        data["special_moves"] = validate_abilities(data["special_moves"])
    if "reaction_policy" in data and not isinstance(data["reaction_policy"], dict):
        raise NPCError("Reaction policy must be a mapping.")
    if "boss_check_schedule" in data:
        schedule = data["boss_check_schedule"]
        if not isinstance(schedule, list) or any(
            type(turn) is not int or turn < 1 for turn in schedule
        ):
            raise NPCError("Boss check schedule must list positive turn numbers.")
        data["boss_check_schedule"] = sorted(set(schedule))
    with transaction.atomic():
        blueprint = _locked(actor, blueprint, manage=True)
        profile, _ = NPCCombatProfile.objects.get_or_create(blueprint=blueprint)
        for key, value in data.items():
            setattr(profile, key, value)
        profile.save()
        return profile


def partner_model(setting, model):
    label = conf.get(setting)
    cfg = next((cfg for cfg in apps.get_app_configs() if cfg.label == label), None)
    return cfg.get_model(model) if cfg else None


def link_plot(actor, blueprint, ref, *, unlink=False):
    model = partner_model("NPCS_PLOTS_APP_LABEL", "PlotThread")
    if model is None:
        raise NPCError("Plot threads are not installed.")
    with transaction.atomic():
        blueprint = _locked(actor, blueprint)
        try:
            thread = model.objects.get(plot_number=int(str(ref).lstrip("#")))
        except (ValueError, model.DoesNotExist) as exc:
            raise NPCError("No accessible plot thread matches that id.") from exc
        if not thread.can_link(actor):
            raise NPCError("No accessible plot thread matches that id.")
        if unlink:
            if not can_manage(actor, blueprint):
                raise NPCError("Only the NPC owner or staff may unlink it.")
            PlotNPCLink.objects.filter(blueprint=blueprint, thread_id=thread.pk).delete()
        else:
            PlotNPCLink.objects.get_or_create(
                blueprint=blueprint,
                thread_id=thread.pk,
                defaults={"linked_by_id_snapshot": actor.pk},
            )
        return thread


def history(actor, blueprint):
    require(actor)
    from .integrations import visible_scene

    lines = []
    for record in blueprint.spawns.all()[:50]:
        lines.append(
            f"Spawn #{record.pk}: {record.spawned_at.date()} by {record.spawner_name} ({'despawned' if record.despawned_at else 'active'})"
        )
        for appearance in record.scenes.all():
            scene = visible_scene(actor, appearance.scene_id)
            if scene:
                lines.append(f"  Scene #{scene.scene_number}: {scene.title}")
    return lines
