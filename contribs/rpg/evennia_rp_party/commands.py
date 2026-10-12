# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import CombatError

from . import services


class CmdParty(MuxCommand):
    """Optional tactical teams within a combat side, with no leader or roles.

    +party                         Roster, Formation and damage boost
    +party/create name             Create and join, initially Flex
    +party/join identity           Join/transfer yourself; side stays fixed
    +party/leave                   Become unpartied
    +party/rename name             Any current member can rename
    +party/invite character        Invitation; never enrolls or moves them
    +party/accept|decline          Answer a Party invitation
    +party/formation front|back|flex[=on|off]
                                   Explicit standing permission for Cover
    +party/dissolve [identity]     Propose; empty/unavailable parties clean up
    +party/agree|veto [identity]   Agree to or reject dissolution
    +party/cover defender=token[,resist|overpower,counter,empower,domain]
    +party/coverodds defender=token  Public estimates; accepts nothing
    +party/chat message            Private transient OOC; no saved history

    Add /as to act as a permitted NPC: +party/create/as NPC=Name;
    +party/cover/as NPC=defender;token[,reaction,counter,empower,domain].
    Back Cover starts off. A Cover immediately accepts Resist/Overpower;
    it cannot Evade, and it hands the rest of a Burst to the coverer.
    Membership/Formation require clear incoming and outgoing exchanges.
    Party never changes your side, personal turns or combat assessment.
    Synergy and Boss Checks are deferred. See the Party guide for details.
    """

    key = "+party"
    locks = "cmd:all()"
    help_category = "Combat"

    def func(self):
        try:
            switches = [switch for switch in self.switches if switch != "as"]
            if len(switches) > 1:
                raise CombatError("Choose one Party operation. See help +party.")
            operation = switches[0] if switches else "status"
            subject = self.caller
            text = self.args.strip()
            if "as" in self.switches:
                npc_name, sep, text = text.partition("=")
                if not sep:
                    raise CombatError("Use /as NPC=arguments.")
                subject = self.caller.search(npc_name.strip())
                if subject is None:
                    return
                if combat.npc_record(subject) is None:
                    raise CombatError("/as directs permitted NPCs only.")
                text = text.strip()
            if operation == "status":
                self.msg(services.render(self.caller, subject=subject))
            elif operation == "chat":
                services.chat(self.caller, text, subject=subject)
            elif operation in ("cover", "coverodds"):
                defender, sep, choices = text.partition(";" if "as" in self.switches else "=")
                if not sep:
                    raise CombatError(
                        "Use +party/cover defender=token[,reaction,counter,empower,domain]."
                    )
                original = self.caller.search(defender.strip())
                if original is None:
                    return
                parts = [part.strip() for part in choices.split(",")]
                if not 1 <= len(parts) <= 5:
                    raise CombatError("See help +party for Cover options.")
                parts += [""] * (5 - len(parts))
                if parts[3] not in ("", "empower"):
                    raise CombatError("The fourth Cover option is empower or empty.")
                result = services.cover(
                    self.caller,
                    original,
                    parts[0],
                    parts[1] or "resist",
                    subject=subject,
                    counter=parts[2] or "balanced",
                    empower=parts[3] == "empower",
                    domain=parts[4],
                    preview=operation == "coverodds",
                )
                if operation == "coverodds":
                    self.msg(result)
            else:
                permission = None
                target = None
                if operation == "formation":
                    text, sep, value = text.partition("=")
                    if sep:
                        if value.strip().lower() not in ("on", "off"):
                            raise CombatError("Cover permission is explicitly on or off.")
                        permission = value.strip().lower() == "on"
                    text = text.strip().lower()
                if operation == "invite":
                    target = self.caller.search(text)
                    if target is None:
                        return
                result = services.change(
                    self.caller,
                    "decline_dissolve" if operation == "veto" else operation,
                    text,
                    subject=subject,
                    cover=permission,
                    target=target,
                )
                self.msg(f"Party {operation}: {combat.plain(result)}.")
        except (CombatError, ValueError, LookupError) as exc:
            self.msg(combat.plain(exc, 500))


class PartyCmdSet(CmdSet):
    key = "RPParty"

    def at_cmdset_creation(self):
        self.add(CmdParty)
