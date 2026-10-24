# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One-switch action commands, persistent modifiers and private tactics."""

from decimal import Decimal, InvalidOperation

from evennia import CmdSet

from . import services, tactics
from .command_syntax import CombatCommand
from .data import CombatError


class CmdCombat(CombatCommand):
    """Manage a consent-based fight; use dedicated commands to act.

    +combat                         Status, private queue and armed modifiers
    +combat/setup <reason>          Start a fight in this room
    +combat/join <side>[=<boss>]     Join explicitly; default boss 1, cap 4
    +combat/invite <name>=<side>     Invite; never enroll another PC
    +combat/refuse                  Decline an invitation
    +combat/odds <token>             Private reaction estimates
    +combat/cancel <token>           Cancel an unaccepted packet
    +combat/auto on                 Enable automatic reactions (/auto off disables)
    +combat/act                     Invoke one automatic outgoing action
    +combat/posed                   Acknowledge your owed pose
    +combat/fade                    Step out; /join restores your place
    +combat/withdraw                Withdraw from accounting
    +combat/accept <request>         Accept a request or revival
    +combat/decline <request>        Decline a request or revival
    +combat/revive accept            Automatically accept allied revival (ask resets)
    +combat/retract                 Withdraw an unaccepted revival
    +combat/unlock                  Announce a build correction; clear queues first
    +combat/relock                  Validate and announce the corrected build lock
    +combat/cap <number>             Set your join cap; after joining, only reduce it
    +combat/unignore <character>     Remove account-wide ignore
    +combat/rollback <seq>=<reason>  Staff recovery
    +combat/journal                 Retained public summaries
    +combat/result <exchange>        Recover committed results
    +combat/mine                    Open/shelved fights where you retain a place
    +combat/help                    Installed partner help

    +pass spends one action without an exchange or resource rewards, recovers
    Resist pressure, ticks conditions and owes a pose. Armed modifiers survive.
    After +npc/puppet, ordinary commands act as and identify that NPC.
    """

    key = "+combat"
    literal_switches = ("setup",)
    switch_options = (
        "setup",
        "join",
        "invite",
        "refuse",
        "odds",
        "cancel",
        "auto",
        "act",
        "posed",
        "fade",
        "withdraw",
        "accept",
        "decline",
        "revive",
        "retract",
        "unlock",
        "relock",
        "cap",
        "unignore",
        "rollback",
        "journal",
        "result",
        "help",
        "mine",
    )

    def run(self):
        op = self.switches[0] if self.switches else ""
        actor, subject = self.caller, self.subject
        if not op:
            self.msg(services.render(actor, subject=subject))
        elif op == "mine":
            self.msg(services.mine(actor, subject=subject))
        elif op == "help":
            self.msg(services.help_for(actor))
        elif op == "setup":
            services.setup(actor, reason=self.args.strip())
        elif op == "join":
            services.join(
                actor, self.lhs.strip(), subject=subject, boss=int(self.rhs) if self.rhs else 1
            )
        elif op == "cap":
            services.prepare_cap(actor, int(self.args), subject=subject)
            self.msg("Personal Turn Limit set.")
        elif op == "invite":
            target = actor.search(self.lhs.strip())
            if target:
                self.msg(services.invite(subject, target, (self.rhs or "").strip()))
        elif op == "refuse":
            services.refuse(subject)
        elif op == "odds":
            self.msg(services.odds(actor, self.args.strip(), subject=subject))
        elif op == "act":
            self.msg(services.auto_act(actor, subject=subject))
        elif op == "unignore":
            target = actor.search(self.args.strip())
            if target:
                services.unignore(actor, target)
        elif op == "rollback":
            services.rollback(actor, int(self.lhs), self.rhs or "")
        elif op == "journal":
            self.msg(services.journal(actor))
        elif op == "result":
            self.msg(services.result(actor, self.args.strip()))
        else:
            if op in ("unlock", "relock") and self.args.strip():
                raise CombatError(
                    "Build corrections announce only unlock/relock. Use "
                    + self.key
                    + "/"
                    + op
                    + "."
                )
            services.control(
                actor,
                op,
                subject=subject,
                argument=self.args.strip(),
            )


class CmdAction(CombatCommand):
    """Declare an action; target names are comma-separated like items.

    +attack[/reaching] <targets>=<move>[/<domain>]
    +spell[/penetrating] <targets>=<move>[/<domain>]
    +assist <ally>[=<move>[/<domain>]]
    +dispirit <opponent>[=<move>[/<domain>]]

    Attack/Spell switches: reaching, penetrating, subtle (unique prefixes).
    Arm modifiers with +empower, +burst, +callshot, +waive or +surge first.
    Cancellation preserves them; an eligible executed action consumes them.
    """

    key = "+attack"
    action = "attack"
    switch_options = ("reaching", "penetrating", "subtle")

    def run(self):
        targets = [self.caller.search(name.strip()) for name in self.lhs.split(",") if name.strip()]
        if not targets:
            raise CombatError("Name at least one target.")
        if any(target is None for target in targets):
            return
        move, _, domain = (
            self.rhs or (self.action if self.action in ("assist", "dispirit") else "balanced")
        ).partition("/")
        self.msg(
            services.declare(
                self.caller,
                targets,
                move.strip(),
                subject=self.subject,
                action=self.action,
                bet=self.switches[0] if self.switches else "",
                domain=domain.strip(),
            )
        )


class CmdSpell(CmdAction):
    """Cast a spell against one or more opponents.

    +spell[/penetrating] <targets>=<move>[/<domain>]

    RPS switches: reaching, penetrating, subtle; unique prefixes work.
    Arm +empower, +burst, +callshot or +surge before the action.
    """

    key = "+spell"
    action = "spell"


class CmdAssist(CmdAction):
    """Help another ally with a standard Assist or equipped Signature.

    +assist <ally>[=<move>[/<domain>]]

    A Heal can offer revival. Arm +waive before a Medicine revival to waive
    recovery. Other eligible modifiers, such as +empower and +surge, arm separately.
    """

    key = "+assist"
    action = "assist"
    switch_options = ()


class CmdDispirit(CmdAssist):
    """Unsettle an opponent without an incoming reaction.

    +dispirit <opponent>[=<move>[/<domain>]]

    Eligible +empower and +surge modifiers arm separately.
    """

    key = "+dispirit"
    action = "dispirit"


class CmdReact(CombatCommand):
    """Accept one reaction, using an armed +counter and +empower if eligible.

    +react/evade <token>[/<domain>]
    +react/resist <token>[/<domain>]
    +react/overpower <token>[/<domain>]
    +react/read <token>=<domain>
    """

    key = "+react"
    switch_options = ("evade", "resist", "overpower", "read")

    def run(self):
        if len(self.switches) != 1:
            raise CombatError("Choose Evade, Resist or Overpower as the switch.")
        if self.switches == ["read"]:
            self.msg(
                services.read(
                    self.caller,
                    self.lhs.strip(),
                    (self.rhs or "insight").strip(),
                    subject=self.subject,
                )
            )
            return
        token, _, domain = self.args.strip().partition("/")
        services.react(self.caller, token, self.switches[0], subject=self.subject, domain=domain)


class CmdModifier(CombatCommand):
    """Arm the next eligible action; /off disarms. Passing/cancelling preserves it.

    +empower      +burst      +callshot      +waive
    +counter <move>           +surge [<target>]
    +empower/off (the same switch is available on every modifier)
    """

    key = "+empower"
    switch_options = ("off",)

    def run(self):
        flag = self.key.lstrip("+")
        value = self.args.strip() or (
            "balanced" if flag == "counter" else "" if flag == "surge" else True
        )
        if flag not in ("counter", "surge") and self.args.strip():
            raise CombatError("This modifier takes no arguments.")
        if flag == "surge" and value:
            target = self.caller.search(value)
            if target is None:
                return
            value = str(target.pk)
        services.arm(self.caller, flag, value, subject=self.subject, off=bool(self.switches))
        self.msg(f"{flag.capitalize()} {'disarmed' if self.switches else 'armed'}.")


class CmdBurst(CmdModifier):
    """Arm a Burst for your next eligible single-target Attack or Spell.

    +burst
    +burst/off

    Press subsequent hits with +press, or end the chain with +stop.
    Passing and cancellation preserve the flag; an executed hit consumes it.
    """

    key = "+burst"


class CmdCallshot(CmdModifier):
    """Arm Calling the Shot for your next eligible RPS attack.

    +callshot
    +callshot/off

    Requires the equipped Ability when the attack is declared. The bet is
    announced publicly. Passing and cancellation preserve the flag.
    """

    key = "+callshot"


class CmdCounter(CmdModifier):
    """Choose the counter for your next Overpower reaction or Cover.

    +counter <move>
    +counter/off

    Use a standard tier or equipped Attack/Spell Signature. Evade, Resist,
    passing and cancellation preserve it; a resolved eligible reaction consumes it.
    """

    key = "+counter"


class CmdWaive(CmdModifier):
    """Arm Medicine's alternative revival: waive recovery without cleansing.

    +waive
    +waive/off

    Declare a reviving Heal using Medicine. Other actions, passing and
    cancellation preserve the flag; the executed revival consumes it.
    """

    key = "+waive"


class CmdSurge(CmdModifier):
    """Arm Party Team Surge for your next eligible action or pressed hit.

    +surge [<target>]
    +surge/off

    A named target must be among that action's targets; otherwise the first
    is boosted. Passing preserves the flag. Cancellation refunds the reservation
    and preserves it; an executed eligible packet consumes it.
    """

    key = "+surge"


class CmdPress(CombatCommand):
    """Press an open Burst (+press), stop it (+stop), or spend an action (+pass)."""

    key = "+press"
    operation = "press"

    def run(self):
        if self.args.strip():
            raise CombatError("This action takes no arguments.")
        services.control(self.caller, self.operation, subject=self.subject)


class CmdStop(CmdPress):
    """End an open Burst without declaring another hit.

    +stop

    This finishes the already executed exchange. Unused armed modifiers stay armed.
    """

    key = "+stop"
    operation = "stop"


class CmdPass(CmdPress):
    """Spend one action without declaring an outgoing exchange.

    +pass

    Clear incoming/outgoing exchanges and your owed pose first. Passing
    advances the condition clock once, ticks Poison, expires conditions/stances,
    recovers Resist pressure and owes a pose. It clears revival recovery.
    It grants no Reserves, Spirit, Transcendence, Measured Tempo or Synergy.
    Armed modifiers survive. Staggered's skipped turn adds no tick or rewards.
    """

    key = "+pass"
    operation = "pass"


class CmdCombatStory(CombatCommand):
    """Publicly attributed storyteller controls, available to ordinary players.

    +combatstory/pause [reason]         Anyone may pause at any time
    +combatstory/resume [reason]        Resume a normal pause
    +combatstory/end [reason]           Ends once present players accept
    +combatstory/shelve [reason]        Set the fight aside; everyone Fades
    +combatstory/shelved                Shelved fights you or this room had
    +combatstory/unshelve number        Bring one back here; players rejoin
    +combatstory/imbalance description
    +combatstory/vitality name=value # <reason>   Story damage/healing
    +combatstory/spirit name=value # <reason>     Spirit displayed as decimal
    +combatstory/requestcap name=cap # <reason>   Lower a personal Turn Limit
    +combatstory/requestreturn name=Vitality # <reason> Return to the fight
    +combatstory/condition name=condition # <reason>
    +combatstory/clearcondition name=condition # <reason>
    +combatstory/template blueprint[/boss]=side Spawn an allowed template
    +combatstory/enrollnpc name[/boss]=side     Enroll an allowed NPC
    +combatstory/removenpc name                    Fade an allowed NPC
    +combatstory/auto name=on                      NPC reactions only (off disables)
    +combatstory/act names                         One action per allowed NPC

    Everyone can tell a story. A change to another player's character is a
    request they +combat/accept or /decline; NPCs you may direct change at
    once. These commands never enroll unwilling PCs or grant NPC
    permissions. Staff rollback remains +combat/rollback.
    """

    key = "+combatstory"
    literal_switches = ("pause", "resume", "end", "shelve", "imbalance")
    locks = "cmd:all()"
    help_category = "Combat"

    switch_options = (
        "pause",
        "resume",
        "end",
        "shelve",
        "shelved",
        "unshelve",
        "imbalance",
        "vitality",
        "spirit",
        "requestcap",
        "requestreturn",
        "condition",
        "clearcondition",
        "template",
        "enrollnpc",
        "removenpc",
        "auto",
        "act",
    )

    def run(self):
        try:
            if len(self.switches) != 1:
                raise CombatError("Choose one storyteller switch. See help +combatstory.")
            operation = self.switches[0]
            target, value, reason = None, None, self.args.strip()
            if operation == "shelved":
                self.msg(services.shelved(self.caller))
                return
            if operation == "unshelve":
                services.unshelve(self.caller, int(self.args.strip().lstrip("#")))
                return
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
                    name, _, multiplier = self.lhs.partition("/")
                    side = (self.rhs or "").strip()
                    boss = int(multiplier) if multiplier else 1
                    cap = None
                    if operation == "template":
                        blueprint = npcs.find_blueprint(name.strip())
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
                        target = self.caller.search(name.strip())
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
                value, _, reason = (self.rhs or "").partition(" # ")
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


class CmdTactics(CombatCommand):
    """Edit private presets independently of selecting or enabling automation.

    +tactics
    +tactics/set <preset>/<field>=<value>
    +tactics/use <preset>
    +tactics/delete <preset>

    Fields: appetite, preferred_reaction, preferred_moves, rps_appetite,
    target_policy, action_weights. Preferred moves are comma-separated keys.
    Weights are like action/weight items: standard/70,special/30.
    Deleting the active preset restores Balanced defaults. Auto-Resolve and
    already committed reactions are unchanged by any library operation.
    """

    key = "+tactics"
    switch_options = ("set", "use", "delete")

    def run(self):
        from evennia_links import runtime

        from .models import Tactics

        if not runtime.get("RP_COMBAT_TACTICS_REVEALED"):
            raise CombatError("Tactics are not available yet.")
        op = self.switches[0] if self.switches else ""
        if op == "set":
            name, sep, field = self.lhs.partition("/")
            if not sep or not name.strip() or self.rhs is None:
                raise CombatError("Use +tactics/set <preset>/<field>=<value>.")
            tactics.set_field(self.subject, name.strip(), field.strip(), self.rhs)
            self.msg("Tactics saved. Selection and Auto-Resolve are unchanged.")
        elif op == "use":
            row = tactics.use(self.subject, self.args.strip())
            self.msg(f"Active Tactics: {services.plain(row.name)}. Auto-Resolve is unchanged.")
        elif op == "delete":
            tactics.delete(self.subject, self.args.strip())
            self.msg("Tactics deleted. Auto-Resolve is unchanged.")
        else:
            self.msg(
                "\n".join(
                    f"{services.plain(row.name)}: defense {row.appetite}; RPS {row.rps_appetite}; "
                    f"preferred reaction {row.preferred_reaction or 'none'}; {'active' if row.active else 'saved'}."
                    for row in Tactics.objects.filter(character=self.subject)
                )
                or "No saved Tactics; Balanced defaults apply."
            )


ACTION_COMMANDS = (
    CmdAction,
    CmdSpell,
    CmdAssist,
    CmdDispirit,
    CmdReact,
    CmdModifier,
    CmdBurst,
    CmdCallshot,
    CmdCounter,
    CmdWaive,
    CmdSurge,
    CmdPress,
    CmdStop,
    CmdPass,
)


class CombatCmdSet(CmdSet):
    key = "RPCombat"

    def at_cmdset_creation(self):
        self.add(CmdCombat)
        self.add(CmdCombatStory)
        self.add(CmdTactics)
        for command in ACTION_COMMANDS:
            self.add(command)
        from .improv_commands import CmdImprov

        self.add(CmdImprov)
