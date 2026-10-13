# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Manual narrative Boss Checks; players control pacing and participation."""

from evennia.commands.default.muxcommand import MuxCommand
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import CombatError

from . import boss_services as services


def options(text):
    parts = [part.strip() for part in text.split(";")]
    values = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not key or key in values:
            raise CombatError("Give each Check option once.")
        if not sep and key not in ("pass", "fail"):
            raise CombatError("Check options use key=value.")
        values[key] = value if sep else True
    return parts[0], values


def verdict(values):
    if "pass" in values and "fail" in values:
        raise CombatError("Choose pass or fail, not both.")
    if "pass" in values:
        values.pop("pass")
        return True
    if "fail" in values:
        values.pop("fail")
        return False
    return None


class CmdBossCheck(MuxCommand):
    """Offer a fair dramatic challenge to one or more opposing Parties.

    +bosscheck                         Inspect Check status
    +bosscheck parties=type[;difficulty=balanced][;value=...]
    +bosscheck parties=special;requirement=...;hint=...
    +bosscheck parties=contest;approaches=stat,stat[/tag][;roll=rating]
    +bosscheck/preview id[;pass|fail]    Preview current consequences/token
    +bosscheck/resolve id=token[;pass|fail][;ack=public reason]
    +bosscheck/withdraw id[=reason]     Cancel only your participation
    +bosscheck/cancel id[=reason]       Cancel your Party's pending Check
    +bosscheck/roll id=stat[/tag]       One free bound Contest response
    +bosscheck/allow id=member;stat     Boss approves an approach before rolling

    Types: Tank, DPS, Support, Pressure, Special, Contest.
    Difficulty: easy, balanced (default), hard. Value overrides the per-member
    Tank/DPS amount, Support percentage, Pressure Spirit threshold, or Contest
    success fraction. Special needs explicit pass/fail on preview and resolve,
    with ack=public explanation when resolving.
    Boss Mode x2+ and clear boss queues are required to issue. One Check per
    Party can be pending; one boss may challenge multiple Parties at once.
    Issuance/response rolls spend no actions. No automatic resolution.
    Add /as NPC=... to direct an NPC you are permitted to control.
    Pending cancellation is free; committed consequences require staff recovery.
    """

    key = "+bosscheck"
    locks = "cmd:all()"
    help_category = "Combat"

    def func(self):
        try:
            switches = [switch for switch in self.switches if switch != "as"]
            if len(switches) > 1:
                raise CombatError("Choose one Boss Check operation.")
            operation = switches[0] if switches else "issue"
            subject = self.caller
            text = self.args.strip()
            if "as" in self.switches:
                name, sep, text = text.partition("=")
                if not sep:
                    raise CombatError("Use /as NPC=Check arguments.")
                subject = self.caller.search(name.strip())
                if subject is None:
                    return
            if not text and operation in ("issue", "status"):
                from .services import render

                self.msg(render(self.caller, subject=subject))
                return
            if operation in ("cancel", "withdraw"):
                ident, _, reason = text.partition("=")
                result = services.cancel(
                    self.caller,
                    ident.strip(),
                    subject=subject,
                    individual=operation == "withdraw",
                    reason=reason,
                )
            elif operation == "preview":
                ident, values = options(text)
                chosen = verdict(values)
                if values:
                    raise CombatError("Preview accepts only pass/fail for Special.")
                view = services.preview(self.caller, ident, subject=subject, verdict=chosen)
                self.msg("\n".join(combat.plain(line, 1000) for line in view["lines"]))
                return
            elif operation == "resolve":
                ident, sep, rest = text.partition("=")
                if not sep:
                    raise CombatError("Preview first, then /resolve id=token[;ack=reason].")
                token, values = options(rest)
                chosen = verdict(values)
                acknowledgment = values.pop("ack", "")
                if values:
                    raise CombatError("Resolve accepts pass/fail and ack only.")
                result = services.resolve(
                    self.caller,
                    ident.strip(),
                    token,
                    subject=subject,
                    verdict=chosen,
                    acknowledgment=acknowledgment,
                )
                self.msg(f"Check {ident.strip()}: {'passed' if result['passed'] else 'failed'}.")
                return
            elif operation == "roll":
                ident, sep, name = text.partition("=")
                if not sep:
                    raise CombatError("Use /roll id=declared stat[/tag].")
                result = services.roll(self.caller, ident.strip(), name.strip(), subject=subject)
                self.msg(f"Contest response: {'pass' if result['success'] else 'fail'}.")
                return
            elif operation == "allow":
                ident, sep, rest = text.partition("=")
                name, separator, approach = rest.partition(";")
                if not sep or not separator:
                    raise CombatError("Use /allow id=member;stat[/tag].")
                member = self.caller.search(name.strip())
                if member is None:
                    return
                result = services.allow(
                    self.caller, ident.strip(), member, approach.strip(), subject=subject
                )
            elif operation == "issue":
                names, sep, rest = text.partition("=")
                if not sep:
                    raise CombatError("Use +bosscheck Party identities=type[;options].")
                kind, values = options(rest)
                difficulty = values.pop("difficulty", "balanced").lower()
                approaches = tuple(
                    value.strip()
                    for value in values.pop("approaches", "").split(",")
                    if value.strip()
                )
                roll = values.pop("roll", None)
                result = services.issue(
                    self.caller,
                    [name.strip() for name in names.split(",")],
                    kind.lower(),
                    subject=subject,
                    difficulty=difficulty,
                    options=values,
                    approaches=approaches,
                    roll_difficulty=roll,
                )
                self.msg(f"Boss Checks issued: {', '.join(result)}.")
                return
            else:
                raise CombatError("See help +bosscheck for manual Check operations.")
            self.msg(f"Boss Check {operation}: {result}.")
        except (CombatError, ValueError, LookupError) as exc:
            self.msg(combat.plain(exc, 500))
