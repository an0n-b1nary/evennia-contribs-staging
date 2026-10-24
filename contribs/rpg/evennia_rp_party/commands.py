# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Party membership and dedicated Cover commands using current puppet state."""

from evennia import CmdSet
from evennia_rp_combat import services as combat
from evennia_rp_combat.command_syntax import CombatCommand
from evennia_rp_combat.data import CombatError

from . import rules, services


class CmdParty(CombatCommand):
    """Optional tactical teams within a side; ordinary commands honor NPC portrayal.

    +party                         Roster, Formation, damage boost and Synergy
    +party/create <name>            Create and join, initially Flex
    +party/join <identity>          Join or transfer yourself
    +party/leave                    Become unpartied
    +party/rename <name>            Rename your Party
    +party/invite <character>       Invitation; never enrolls anyone
    +party/accept                   Accept an invitation (/decline refuses)
    +party/formation <position>     Front, Back or Flex
    +party/coveron                  Grant standing Cover permission
    +party/coveroff                 Revoke standing Cover permission
    +party/dissolve [<identity>]    Propose dissolution
    +party/agree [<identity>]       Agree (/veto refuses)
    +party/coverodds <defender>=<token>   Preview Cover without accepting
    +party/chat <message>           Private transient OOC

    Use +cover/resist or +cover/overpower to intercept. Arm +surge before
    an ordinary action or +press; /off disarms it. Passing preserves it.
    """

    key = "+party"
    literal_switches = ("chat",)
    switch_options = (
        "create",
        "join",
        "leave",
        "rename",
        "invite",
        "accept",
        "decline",
        "formation",
        "coveron",
        "coveroff",
        "dissolve",
        "agree",
        "veto",
        "coverodds",
        "chat",
    )

    def run(self):
        op = self.switches[0] if self.switches else ""
        if not op:
            self.msg(services.render(self.caller, subject=self.subject))
            return
        text = self.args.strip()
        if op == "chat":
            services.chat(self.caller, text, subject=self.subject)
            return
        if op == "coverodds":
            target = self.caller.search(self.lhs.strip())
            if target:
                self.msg(
                    services.cover(
                        self.caller,
                        target,
                        self.rhs or "",
                        "resist",
                        subject=self.subject,
                        preview=True,
                    )
                )
            return
        cover = None
        if op in ("coveron", "coveroff"):
            cover = op == "coveron"
            text = rules.position(combat.state_for(self.caller), str(self.subject.pk))
            op = "formation"
        target = self.caller.search(text) if op == "invite" else None
        if op == "invite" and target is None:
            return
        result = services.change(
            self.caller,
            "decline_dissolve" if op == "veto" else op,
            text,
            subject=self.subject,
            cover=cover,
            target=target,
        )
        self.msg(f"Party {op}: {combat.plain(result)}.")


class CmdCover(CombatCommand):
    """Intercept a party member's incoming packet; Evade is unavailable.

    +cover/resist <defender>=<token>[/<domain>]
    +cover/overpower <defender>=<token>[/<domain>]

    Arm +counter <move> and +empower first to modify an Overpower counter.
    """

    key = "+cover"
    switch_options = ("resist", "overpower")

    def run(self):
        if len(self.switches) != 1 or not self.rhs:
            raise CombatError("Use +cover/resist <defender>=<token>.")
        original = self.caller.search(self.lhs.strip())
        if original is None:
            return
        token, _, domain = self.rhs.strip().partition("/")
        services.cover(
            self.caller, original, token, self.switches[0], subject=self.subject, domain=domain
        )


class PartyCmdSet(CmdSet):
    key = "RPParty"

    def at_cmdset_creation(self):
        from .boss_commands import CmdBossCheck

        self.add(CmdParty)
        self.add(CmdCover)
        self.add(CmdBossCheck)
