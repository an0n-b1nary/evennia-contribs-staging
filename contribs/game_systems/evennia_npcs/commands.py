# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Blueprint management and explicit, attributed NPC portrayal."""

import json
from functools import lru_cache

from django.apps import apps
from evennia import CmdSet
from evennia.commands.default.account import CmdIC
from evennia.commands.default.general import CmdPose as DefaultPose
from evennia.commands.default.general import CmdSay as DefaultSay
from evennia.commands.default.muxcommand import MuxCommand

from . import services as svc
from .models import NPCBlueprint, NPCPermissionRequest


class CmdNPC(MuxCommand):
    """Create, share and play NPCs. Names refer to blueprints, object #ids to spawns.

    Usage:
      +npc [name|#blueprint]
      +npc/search <text>
      +npc/create <name>=template|unique
      +npc/desc <name>=<description>
      +npc/short <name>=<short description>
      +npc/stats <name>=<stat>:<rating>,...
      +npc/abilities <name>=<stable identifier>,...
      +npc/archive <name>              +npc/restore <name>
      +npc/spawn <name>                +npc/despawn <object #id>
      +npc/puppet <object #id>          +npc/unpuppet
      +npc/fullpuppet <object #id>      +npc/unfullpuppet
      +npc/permit <name>=<character>    +npc/revoke <name>=<character>
      +npc/transfer <name>=<character>
      +npc/request <name>=<reason>     +npc/requests
      +npc/approve <request #id>       +npc/deny <request #id>
      +npc/history <name>
      +npc/plot <name>=<thread #id>     +npc/unplot <name>=<thread #id>
      +npc/profile <name>=<JSON mapping> (separately revealed)

    Templates are open to play; unique NPCs need owner permission and can
    only appear once. Virtual portrayal redirects pose, say, emit, semipose
    and +test while keeping you on your character. Movement or revocation
    ends it. Full puppeting requires a host opt-in. All NPC portrayal names
    the responsible player. /unpuppet and /despawn work while frozen/hidden.
    """

    key = "+npc"
    aliases = ["+npcs"]  # noqa: RUF012
    help_category = "NPCs"
    locks = "cmd:all()"

    def func(self):
        try:
            self.execute()
        except (svc.NPCError, json.JSONDecodeError) as exc:
            self.msg(str(exc))

    def execute(self):
        actor = self.caller
        if len(self.switches) > 1:
            raise svc.NPCError("Use one NPC switch at a time.")
        switch = self.switches[0].lower() if self.switches else ""
        if switch == "unfullpuppet":
            svc.return_from_full(actor, self.session)
            return
        svc.require(actor, cleanup=switch in {"unpuppet", "despawn"})
        if switch == "unpuppet":
            svc.release(actor)
            self.msg("NPC portrayal released.")
            return
        if switch in {"puppet", "fullpuppet", "despawn"}:
            record = svc.find_spawn(actor, self.args, cleanup=switch == "despawn")
            if switch == "despawn":
                svc.despawn(actor, record)
                self.msg("NPC despawned; its history is retained.")
            elif switch == "fullpuppet":
                svc.full_puppet(actor, record, self.session)
            else:
                npc = svc.control(actor, record)
                self.msg(f"Now portraying {svc.attribution(npc)}. Use +npc/unpuppet to stop.")
            return
        if switch in {"approve", "deny"}:
            request = svc.resolve_request(actor, self.args, approved=switch == "approve")
            self.msg(f"Request #{request.pk}: {request.status}.")
            return
        if switch == "requests":
            requests = NPCPermissionRequest.objects.filter(status="pending")
            if not svc.is_staff(actor):
                requests = requests.filter(
                    blueprint__permissions__holder=actor, blueprint__permissions__level="owner"
                )
            self.msg(
                "\n".join(
                    f"#{r.pk}: {r.blueprint.name}, requested by {r.requester_name}: {r.reason}"
                    for r in requests[:50]
                )
                or "No pending NPC requests."
            )
            return
        if switch == "create":
            blueprint = svc.create_blueprint(actor, self.lhs, self.rhs or "unique")
            self.msg(f"Created NPC blueprint #{blueprint.pk}: {blueprint.name} ({blueprint.kind}).")
            return
        if switch == "search" or (not switch and not self.args):
            query = NPCBlueprint.objects.filter(archived=False)
            if switch:
                query = query.filter(name__icontains=self.args.strip())
            self.msg(
                "\n".join(
                    f"#{b.pk}: {b.name} ({b.kind}){' [playable]' if svc.can_play(actor, b) else ''}"
                    for b in query[:50]
                )
                or "No NPC blueprints found."
            )
            return
        blueprint = svc.find_blueprint(self.lhs)
        if not switch:
            self.msg(
                f"#{blueprint.pk}: {blueprint.name} ({blueprint.kind}){' [archived]' if blueprint.archived else ''}\n{blueprint.description}\nStats: {json.dumps(blueprint.stat_block, sort_keys=True)}\nAbilities: {', '.join(blueprint.abilities) or 'none'}"
            )
        elif switch == "spawn":
            record = svc.spawn(actor, blueprint)
            self.msg(
                f"Spawned {blueprint.name}: object #{record.spawned_object_id}. Use +npc/puppet #{record.spawned_object_id}."
            )
        elif switch in {"desc", "short", "stats", "abilities"}:
            value = self.rhs or ""
            if switch == "stats":
                pairs = [pair.strip().partition(":") for pair in value.split(",") if pair.strip()]
                if any(not sep or not rating for _, sep, rating in pairs):
                    raise svc.NPCError("Use stat:rating pairs separated by commas.")
                value = {key.strip(): rating.strip() for key, _, rating in pairs}
            elif switch == "abilities":
                value = [part.strip() for part in value.split(",") if part.strip()]
            field = {
                "desc": "description",
                "short": "short_desc",
                "stats": "stat_block",
                "abilities": "abilities",
            }[switch]
            svc.edit_blueprint(actor, blueprint, **{field: value})
            self.msg("NPC blueprint updated.")
        elif switch in {"archive", "restore"}:
            svc.archive(actor, blueprint, archived=switch == "archive")
            self.msg(f"NPC {'archived' if switch == 'archive' else 'restored'}.")
        elif switch in {"permit", "revoke", "transfer"}:
            if not self.rhs:
                raise svc.NPCError("Supply a character after =.")
            holder = actor.search(self.rhs, global_search=True)
            if holder:
                if switch == "transfer":
                    svc.transfer(actor, blueprint, holder)
                else:
                    svc.permit(actor, blueprint, holder, revoke=switch == "revoke")
                self.msg("NPC permissions updated.")
        elif switch == "request":
            request = svc.request_permission(actor, blueprint, self.rhs or "")
            self.msg(f"Request #{request.pk}: {request.status}.")
        elif switch == "history":
            self.msg("\n".join(svc.history(actor, blueprint)) or "No appearances yet.")
        elif switch in {"plot", "unplot"}:
            thread = svc.link_plot(actor, blueprint, self.rhs or "", unlink=switch == "unplot")
            self.msg(
                f"NPC {'unlinked from' if switch == 'unplot' else 'linked to'} plot #{thread.plot_number}."
            )
        elif switch == "profile":
            svc.edit_profile(actor, blueprint, json.loads(self.rhs or "{}"))
            self.msg("NPC combat profile saved. Combat actions require a combat provider.")
        else:
            raise svc.NPCError("Unknown NPC switch. See help +npc.")


class PortrayalMixin:
    """Apply only to explicitly supported commands, never arbitrary execution."""

    npc_pose_type = "pose"

    def func(self):
        try:
            npc, _ = svc.controlled(self.caller)
            if npc is None:
                if not callable(getattr(self.caller, "record_pose", None)):
                    if self.npc_pose_type == "pose":
                        return DefaultPose.func(self)
                    if self.npc_pose_type in {"semipose", "emit"}:
                        if self.caller.location and self.args:
                            body = (
                                f"{self.caller.key}{self.args}"
                                if self.npc_pose_type == "semipose"
                                else self.args
                            )
                            self.caller.location.msg_contents(body, from_obj=self.caller)
                        return
                return super().func()
            svc.portray(self.caller, self.args.strip(), pose_type=self.npc_pose_type)
        except svc.NPCError as exc:
            self.msg(str(exc))


if apps.is_installed("evennia_posing"):
    from evennia_posing.commands import CmdEmit as BaseEmit
    from evennia_posing.commands import CmdPose as BasePose
    from evennia_posing.commands import CmdSemipose as BaseSemipose
else:
    BasePose = DefaultPose

    class BaseEmit(MuxCommand):
        key = "emit"

        def func(self):
            if self.caller.location and self.args:
                self.caller.location.msg_contents(self.args, from_obj=self.caller)

    class BaseSemipose(BaseEmit):
        key = "semipose"
        aliases = [";"]  # noqa: RUF012

        def func(self):
            if self.caller.location and self.args:
                self.caller.location.msg_contents(
                    f"{self.caller.key}{self.args}", from_obj=self.caller
                )


class CmdNPCPose(PortrayalMixin, BasePose):
    pass


class CmdNPCSay(PortrayalMixin, DefaultSay):
    npc_pose_type = "say"


class CmdNPCEmit(PortrayalMixin, BaseEmit):
    npc_pose_type = "emit"


class CmdNPCSemipose(PortrayalMixin, BaseSemipose):
    npc_pose_type = "semipose"


@lru_cache(maxsize=1)
def contest_command():
    """Called only with the optional contest app installed."""
    from evennia_rp_contest.commands import CmdTest

    class CmdNPCTest(CmdTest):
        def func(self):
            player = self.caller
            try:
                npc, _ = svc.controlled(player)
                if npc is not None:
                    if self.switches:
                        raise svc.NPCError("Release NPC portrayal to manage or review challenges.")
                    from .integrations import require_scene_access

                    require_scene_access(npc, svc.record_for(npc).controller)
                    svc.note_activity(npc, svc.record_for(npc).controller)
                    npc.ndb.npc_feedback_actor = player
                    self.caller = npc
                return super().func()
            except svc.NPCError as exc:
                self.msg(str(exc))
            finally:
                if self.caller != player:
                    self.caller.ndb.npc_feedback_actor = None
                self.caller = player

        def msg(self, text=None, **kwargs):
            caller = self.caller
            if caller.tags.has("npc", category="npc_system"):
                record = svc.record_for(caller)
                if record and record.controller and not caller.account:
                    return record.controller.msg(text, **kwargs)
            return super().msg(text, **kwargs)

    return CmdNPCTest


class NPCCmdSet(CmdSet):
    key = "NPCCmdSet"

    def at_cmdset_creation(self):
        self.add(CmdNPC)
        self.add(CmdNPCPose)
        self.add(CmdNPCSay)
        self.add(CmdNPCEmit)
        self.add(CmdNPCSemipose)
        self.add(CmdNPCIC)
        if apps.is_installed("evennia_rp_contest"):
            self.add(contest_command())


class CmdNPCIC(CmdIC):
    """Preserve the login character when an NPC puppet attempt is refused.

    Evennia's stock CmdIC stores its target as _last_puppet even when
    account.puppet_object() refused and returned without switching.
    """

    def func(self):
        account = self.caller
        previous = account.db._last_puppet
        try:
            return super().func()
        finally:
            puppet = self.session.puppet if self.session else None
            if puppet and not puppet.tags.has("npc", category="npc_system"):
                account.db._last_puppet = puppet
            else:
                last = account.db._last_puppet
                if last and last.tags.has("npc", category="npc_system"):
                    account.db._last_puppet = (
                        previous
                        if previous and not previous.tags.has("npc", category="npc_system")
                        else None
                    )


class NPCAccountCmdSet(CmdSet):
    key = "NPCAccountCmdSet"

    def at_cmdset_creation(self):
        self.add(CmdNPCIC)


class NPCFullCmdSet(NPCCmdSet):
    """An immersive NPC has portrayal commands, never PC economy/build commands."""

    key = "NPCFullCmdSet"

    def at_cmdset_creation(self):
        from evennia.commands.default.general import CmdInventory, CmdLook
        from evennia.commands.default.help import CmdHelp

        super().at_cmdset_creation()
        self.add(CmdLook)
        self.add(CmdInventory)
        self.add(CmdHelp)
