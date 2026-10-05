# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player-led +test and challenge management; full breakdowns stay staff-only."""

import json

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from evennia_rp_contest import narration, permissions, services
from evennia_rp_contest.expiry import sweep_idle
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.parsing import ContestError, number, parse_challenge, parse_test


class CmdTest(MuxCommand):
    """Test a stat, optionally with a domain or element. No rewards are awarded.

    Usage:
      +test [#n=]<stat>[/<tag>][~comment]
      +test/set[/once] <difficulty>[=<stat>[/<tag>]]~<prompt>
      +test/edit #n=<difficulty>[=<stat>[/<tag>]]~<prompt>
      +test/once #n
      +test/void #n/<attempt id>[~reason]
      +test/close #n
      +test/list
      +test/history [#n]
      +test/review [#n]                 (staff)

    Suggestions are guidance: choose any approach. Alternatives and retries
    are announced. /void uses the attempt id in /history, not its retry number.
    A voided attempt remains visible and no longer blocks /once. Use
    kind:key for a tag with an ambiguous spelling, e.g. element:fire.
    """

    key = "+test"
    help_category = "Roleplay"
    locks = "cmd:all()"
    switch_options = ("set", "once", "edit", "void", "close", "list", "history", "review")

    def func(self):
        try:
            self.execute()
        except ContestError as exc:
            self.msg(str(exc))

    def execute(self):
        caller = self.caller
        args = self.args.strip()
        switches = set(self.switches)
        if len(switches) > 1 and switches != {"set", "once"}:
            raise ContestError("Use one switch, or /set/once.")
        if "set" in switches:
            services.open_challenge(caller, parse_challenge(args, once="once" in switches))
        elif "edit" in switches:
            ref, sep, body = args.partition("=")
            if not sep:
                raise ContestError("Usage: +test/edit #n=<difficulty>[=<stat>[/<tag>]]~<prompt>")
            challenge = services.find_challenge(caller, number(ref), open_only=True)
            services.edit_challenge(caller, challenge, parse_challenge(body))
        elif "void" in switches:
            body, _, reason = args.partition("~")
            ref, sep, attempt = body.partition("/")
            if not sep:
                raise ContestError("Usage: +test/void #n/<attempt id>[~reason]")
            challenge = services.find_challenge(caller, number(ref))
            services.void_attempt(caller, challenge, number(attempt), reason=reason)
        elif switches & {"once", "close"}:
            challenge = services.find_challenge(caller, number(args), open_only=True)
            if "once" in switches:
                services.set_once(caller, challenge)
            else:
                services.close_challenge(challenge, caller=caller)
        elif "list" in switches:
            room = services.room_for(caller)
            sweep_idle(room=room)
            challenges = Challenge.objects.filter(room=room, status=Challenge.Status.OPEN)
            lines = [
                f"#{c.number} ({c.difficulty}) by {c.set_by_name}{' [once]' if c.once else ''}: {c.description}"
                for c in challenges
            ]
            self.msg(
                "Open challenges:\n" + "\n".join(lines) if lines else "No open challenges here."
            )
        elif switches & {"history", "review"}:
            review = "review" in switches
            if review and not permissions.is_staff(caller):
                raise ContestError("Only staff can review test breakdowns.")
            records = CheckRecord.objects.filter(room=services.room_for(caller))
            if args:
                challenge = services.find_challenge(caller, number(args))
                records = records.filter(challenge=challenge)
            lines = []
            for record in records.order_by("-created_at", "-pk")[:50]:
                line = f"Attempt {record.pk}: {narration.public_text(record)}"
                if record.voided:
                    line += f" [VOID: {record.void_reason}]"
                if review:
                    line += "\n" + json.dumps(record.detail, sort_keys=True, indent=2)
                lines.append(line)
            self.msg("\n".join(lines) if lines else "No tests recorded here.")
        elif args:
            services.perform_test(caller, parse_test(args))
        else:
            self.msg("Usage: +test [#n=]<stat>[/<tag>][~comment]; +test/list for challenges.")


class ContestCmdSet(CmdSet):
    key = "RPContestCmdSet"

    def at_cmdset_creation(self):
        self.add(CmdTest())
