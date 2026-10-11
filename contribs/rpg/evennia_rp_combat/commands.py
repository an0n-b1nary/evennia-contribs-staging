# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Plain-text command surfaces; identical actions for every reading mode."""

import json
from decimal import Decimal, InvalidOperation

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from . import services, tactics
from .data import CombatError


class CmdCombat(MuxCommand):
    """Consent-based RP combat, with personal turns and queued reactions.

    +combat                     Public pace and your private queue/resources
    +combat/setup [reason]       Storyteller setup (available to everyone)
    +combat/join side[=boss,cap]  Explicit acceptance; defaults boss 1, cap 4
    +combat/invite name=side     Invite; never enroll another PC
    +combat/refuse               Decline an invitation without penalty
    +combat/attack names=move[;rps=bet;domain=key;burst;empower]
    +combat/spell names=move     The same options as Attack
    +combat/assist name[=move]   Another ally; special move may Heal
    +combat/dispirit name        An opponent; no incoming reaction
    +combat/improv names=JSON    An improvised move definition
    +combat/react token=evade|resist|overpower[,counter][,empower]
    +combat/read token=domain    Buy Insight/Read before choosing a reaction
    +combat/odds token           Neutral RPS estimates, your own queue only
    +combat/cancel token         Cancel only before your reaction is accepted
    +combat/auto on|off          Opt in/out of automatic incoming reactions
    +combat/act                  Deliberately invoke one Auto-Act exchange
    +combat/press [empower]      Press an open Burst (maximum three hits)
    +combat/stop                 End an open Burst
    +combat/posed                Acknowledge your own RP; grants no RP/XP
    +combat/fade                 Neutral absence; /join restores your state
    +combat/withdraw             Leave accounting remaining Vitality as lost
    +combat/acceptreturn|refusereturn  Answer a storyteller's return request
    +combat/unlock [reason]      Announced correction, clear queues first
    +combat/relock [reason]      Validate and freeze a corrected build
    +combat/cap number           Voluntarily reduce your personal Turn Limit
    +combat/acceptcap|refusecap   Respond to a storyteller's request
    +combat/unignore character   Remove account-wide ignore, including alts
    +combat/rollback seq=reason  Staff only, whole-fight consistent checkpoint
    +combat/journal              Public sequence summaries for recovery
    +combat/result exchange      Recover committed results after reconnect

    Add /npc to direct your currently controlled NPC, e.g. /npc/act. Your PC
    remains separate. Automatic reactions close cancellation on acceptance.
    RPS bets: reaching, penetrating, subtle. No action timer or global rounds.
    """

    key = "+combat"
    locks = "cmd:all()"
    help_category = "Combat"

    def target(self, name):
        return self.caller.search(name.strip())

    def func(self):
        try:
            self.run()
        except (CombatError, ValueError, TypeError, InvalidOperation, json.JSONDecodeError) as exc:
            self.msg(services.plain(exc, 500))

    def run(self):
        switches = list(self.switches)
        subject = self.caller
        if "npc" in switches:
            switches.remove("npc")
            from django.apps import apps

            if not apps.is_installed("evennia_npcs"):
                raise CombatError("The optional NPC partner is not installed.")
            from evennia_npcs.services import NPCError, controlled

            try:
                subject, _ = controlled(self.caller)
            except NPCError as exc:
                raise CombatError(str(exc)) from None
            if subject is None:
                raise CombatError("Take authorized control of an NPC first.")
        if len(switches) > 1:
            raise CombatError("Choose one combat operation, optionally with /npc.")
        operation = switches[0] if switches else ""
        if not operation:
            self.msg(services.render(self.caller, subject=subject))
        elif operation == "setup":
            services.setup(self.caller, reason=self.args.strip())
        elif operation == "join":
            options = [int(v) for v in self.rhs.split(",")] if self.rhs else []
            if len(options) > 2:
                raise CombatError("Use side=boss multiplier,personal cap.")
            services.join(
                self.caller,
                self.lhs.strip(),
                subject=subject,
                boss=options[0] if options else 1,
                turn_limit=options[1] if len(options) > 1 else None,
            )
        elif operation == "invite":
            target = self.target(self.lhs)
            if target:
                self.msg(services.invite(self.caller, target, self.rhs or "opposition"))
        elif operation == "refuse":
            services.refuse(self.caller)
        elif operation in ("attack", "spell", "assist", "dispirit", "improv"):
            targets = [self.target(name) for name in self.lhs.split(",") if name.strip()]
            if not targets or any(target is None for target in targets):
                return
            parts = (
                ["improvised"]
                if operation == "improv"
                else [
                    p.strip()
                    for p in (
                        self.rhs
                        or (operation if operation in ("assist", "dispirit") else "balanced")
                    ).split(";")
                ]
            )
            key = parts[0]
            options = {}
            for part in parts[1:]:
                name, sep, value = part.partition("=")
                if name not in ("rps", "domain", "burst", "empower"):
                    raise CombatError("Unknown move option.")
                options[name] = value if sep else True
            result = services.declare(
                self.caller,
                targets,
                key,
                subject=subject,
                action=operation if operation != "improv" else "attack",
                bet=options.get("rps", ""),
                domain=options.get("domain", ""),
                burst=bool(options.get("burst")),
                empower=bool(options.get("empower")),
                improvised=json.loads(self.rhs) if operation == "improv" else None,
            )
            self.msg(f"{result}")
        elif operation == "react":
            parts = [part.strip() for part in (self.rhs or "").split(",")]
            services.react(
                self.caller,
                self.lhs.strip(),
                parts[0],
                subject=subject,
                counter=next(
                    (p for p in parts[1:] if p != "empower" and not p.startswith("domain=")),
                    "balanced",
                ),
                empower="empower" in parts,
                domain=next(
                    (p.partition("=")[2] for p in parts[1:] if p.startswith("domain=")), ""
                ),
            )
        elif operation == "odds":
            self.msg(services.odds(self.caller, self.args.strip(), subject=subject))
        elif operation == "read":
            self.msg(
                services.read(self.caller, self.lhs.strip(), self.rhs or "insight", subject=subject)
            )
        elif operation == "act":
            self.msg(services.auto_act(self.caller, subject=subject))
        elif operation == "unignore":
            target = self.target(self.args)
            if target:
                services.unignore(self.caller, target)
        elif operation == "rollback":
            services.rollback(self.caller, int(self.lhs), self.rhs or "")
        elif operation == "journal":
            services.require(self.caller)
            script = services.coordinator(self.caller.location)
            self.msg(
                "\n".join(
                    f"{row['sequence']}: {'superseded; ' if row['superseded'] else ''}{row['summary']}"
                    for row in script.db.journal
                )
                or "No recorded transitions."
            )
        elif operation == "result":
            self.msg(services.result(self.caller, self.args.strip()))
        elif operation in (
            "cancel",
            "auto",
            "press",
            "stop",
            "posed",
            "fade",
            "withdraw",
            "unlock",
            "relock",
            "cap",
            "acceptcap",
            "refusecap",
            "acceptreturn",
            "refusereturn",
        ):
            argument = int(self.args) if operation == "cap" else self.args.strip()
            services.control(
                self.caller,
                operation,
                subject=subject,
                argument=argument,
                reason=self.args.strip() if operation in ("unlock", "relock") else "",
            )
        else:
            raise CombatError("Unknown switch. See help +combat.")


class CmdCombatStory(MuxCommand):
    """Publicly attributed storyteller controls, available to ordinary players.

    +combatstory/pause|resume|end [reason]
    +combatstory/imbalance description
    +combatstory/vitality name=value[;reason]   Story damage/healing
    +combatstory/spirit name=value[;reason]     Spirit displayed as decimal
    +combatstory/requestcap name=cap[;reason]   Player accepts or refuses
    +combatstory/requestreturn name=Vitality[;reason] Consent to return
    +combatstory/condition name=condition[;reason]
    +combatstory/clearcondition name=condition[;reason]
    +combatstory/template blueprint=side[,boss,cap] Spawn an allowed template
    +combatstory/enrollnpc name=side[,boss,cap]     Enroll an allowed NPC
    +combatstory/removenpc name                    Fade an allowed NPC
    +combatstory/auto name=on|off                  NPC reactions only
    +combatstory/act names                         One action per allowed NPC

    Everyone can tell a story. These commands never enroll unwilling PCs or
    grant NPC permissions. Staff rollback remains +combat/rollback.
    """

    key = "+combatstory"
    locks = "cmd:all()"
    help_category = "Combat"

    def func(self):
        try:
            if len(self.switches) != 1:
                raise CombatError("Choose one storyteller switch. See help +combatstory.")
            operation = self.switches[0]
            target, value, reason = None, None, self.args.strip()
            if operation in ("template", "enrollnpc", "removenpc", "auto", "act"):
                from django.apps import apps

                if not apps.is_installed("evennia_npcs"):
                    raise CombatError("The optional NPC partner is not installed.")
                from evennia_npcs import services as npcs

                if operation == "act":
                    targets = [self.caller.search(name.strip()) for name in self.args.split(",")]
                    if all(targets):
                        self.msg(services.auto_batch(self.caller, targets))
                    return
                if operation in ("template", "enrollnpc"):
                    parts = [p.strip() for p in (self.rhs or "").split(",")]
                    side = parts[0]
                    boss = int(parts[1]) if len(parts) > 1 else 1
                    cap = int(parts[2]) if len(parts) > 2 else None
                    if operation == "template":
                        blueprint = npcs.find_blueprint(self.lhs.strip())
                        if blueprint.kind != "template":
                            raise CombatError(
                                "Choose a reusable template; enroll a unique NPC explicitly."
                            )
                        target = services.template(
                            self.caller, blueprint, side, boss=boss, turn_limit=cap
                        )
                        self.msg(
                            f"Spawned {services.identity(target)} #{target.pk} on side {services.plain(side)}."
                        )
                    else:
                        target = self.caller.search(self.lhs.strip())
                        if target:
                            if services.npc_record(target) is None:
                                raise CombatError(
                                    "Storytellers enroll NPCs; PCs explicitly join for themselves."
                                )
                            services.join(
                                self.caller,
                                side,
                                subject=target,
                                boss=boss,
                                turn_limit=cap,
                                batch=True,
                            )
                    return
                target = self.caller.search(self.lhs.strip())
                if target:
                    if services.npc_record(target) is None:
                        raise CombatError("This storyteller operation directs permitted NPCs only.")
                    services.control(
                        self.caller,
                        "auto" if operation == "auto" else "fade",
                        subject=target,
                        argument=self.rhs or "",
                    )
                return
            if operation in (
                "vitality",
                "spirit",
                "requestcap",
                "requestreturn",
                "condition",
                "clearcondition",
            ):
                target = self.caller.search(self.lhs.strip())
                if target is None:
                    return
                value, _, reason = (self.rhs or "").partition(";")
                value = (
                    int(Decimal(value) * 100)
                    if operation == "spirit"
                    else int(value)
                    if operation in ("vitality", "requestcap", "requestreturn")
                    else value.strip()
                )
            services.storyteller(self.caller, operation, target=target, value=value, reason=reason)
        except (CombatError, ValueError, LookupError, InvalidOperation) as exc:
            self.msg(services.plain(exc, 500))


class CmdTactics(MuxCommand):
    """Your private reaction preset and independent outgoing RPS appetite.

    +tactics
    +tactics/save name=JSON

    Fields: appetite, preferred_reaction, preferred_moves, rps_appetite,
    target_policy, action_weights. Example:
    +tactics/save Careful={"appetite":"cautious","rps_appetite":"bold"}

    Choosing a preset does not enable automatic reactions. +combat/auto on
    explicitly enables them; +combat/act explicitly invokes one outgoing action.
    """

    key = "+tactics"
    locks = "cmd:all()"
    help_category = "Combat"

    def func(self):
        try:
            from evennia_links import runtime

            if not runtime.get("RP_COMBAT_TACTICS_REVEALED"):
                raise CombatError("Tactics are not available yet.")
            if self.switches == ["save"]:
                values = json.loads(self.rhs or "{}")
                if not isinstance(values, dict):
                    raise CombatError("Use a Tactics object with documented fields.")
                row = tactics.save(self.caller, self.lhs.strip(), **values)
                self.msg(f"Active Tactics: {services.plain(row.name)}. Auto-Resolve is unchanged.")
            elif not self.switches:
                from .models import Tactics

                lines = [
                    f"{services.plain(row.name)}: defense {row.appetite}; RPS {row.rps_appetite}; "
                    f"preferred reaction {row.preferred_reaction or 'none'}; {'active' if row.active else 'saved'}."
                    for row in Tactics.objects.filter(character=self.caller)
                ]
                self.msg("\n".join(lines) or "No saved Tactics; Balanced defaults apply.")
            else:
                raise CombatError("See help +tactics.")
        except (CombatError, ValueError, TypeError) as exc:
            self.msg(services.plain(exc, 500))


class CombatCmdSet(CmdSet):
    key = "RPCombat"

    def at_cmdset_creation(self):
        self.add(CmdCombat)
        self.add(CmdCombatStory)
        self.add(CmdTactics)
