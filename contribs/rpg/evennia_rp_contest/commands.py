# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player-led tests and standalone room challenge management."""

import json

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_rp_contest import narration, permissions, services
from evennia_rp_contest.command_syntax import split_comment
from evennia_rp_contest.expiry import sweep_idle
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.parsing import (
    ContestError,
    approach,
    limited,
    number,
    parse_challenge,
    parse_test,
)


class CmdTest(StrictSwitchMixin, MuxCommand):
    """Test a stat, optionally with a domain or element. No rewards are awarded.

    Usage:
      +test <stat>[/<tag>] [# comment]
      +test #n=<stat>[/<tag>] [# comment]

    An unnumbered test uses the default difficulty. Name a challenge to answer
    it. Suggestions are guidance: choose any approach. Alternatives and retries
    are announced. Tag names are unique across kinds.
    See +challenge for room challenges and history.
    """

    key = "+test"
    help_category = "Roleplay"
    locks = "cmd:all()"

    def func(self):
        try:
            if self.switches:
                raise ContestError("See help +test for usage.")
            if not self.args.strip():
                self.msg(
                    "Usage: +test [#n=]<stat>[/<tag>] [# comment]; +challenge lists challenges."
                )
                return
            services.perform_test(self.caller, parse_test(self.args))
        except ContestError as exc:
            self.msg(str(exc))


class CmdChallenge(StrictSwitchMixin, MuxCommand):
    """Set and manage room challenges; full breakdowns stay staff-only.

    Usage:
      +challenge
      +challenge/new <difficulty>=<prompt>
      +challenge/suggest #n=<stat>[/<tag>]
      +challenge/edit #n=<prompt>
      +challenge/difficulty #n=<difficulty>
      +challenge/once #n
      +challenge/void #n.<attempt id> [# reason]
      +challenge/close #n
      +challenge/history [#n]
      +challenge/review [#n]                 (staff)

    Bare +challenge lists open challenges in this room. Each editing switch
    changes only its own field. /once marks a challenge as one attempt per
    character. /void uses the record id in /history, not its retry number.
    A voided attempt remains visible and no longer blocks /once.
    """

    key = "+challenge"
    help_category = "Roleplay"
    locks = "cmd:all()"
    switch_options = (
        "new",
        "suggest",
        "edit",
        "difficulty",
        "once",
        "void",
        "close",
        "history",
        "review",
    )

    def func(self):
        try:
            self.execute()
        except ContestError as exc:
            self.msg(str(exc))

    def execute(self):
        caller = self.caller
        args = self.args.strip()
        switches = set(self.switches)
        if len(switches) > 1 or switches - set(self.switch_options):
            raise ContestError("Use one switch from help +challenge.")
        if "new" in switches:
            services.open_challenge(caller, parse_challenge(args))
        elif switches & {"suggest", "edit", "difficulty"}:
            ref, sep, value = args.partition("=")
            switch = next(iter(switches))
            if not sep or not value.strip():
                raise ContestError(f"Usage: +challenge/{switch} #n=<value>")
            challenge = services.find_challenge(caller, number(ref), open_only=True)
            services.require_manager(caller, challenge)
            if switch == "suggest":
                stat, tag = approach(value)
                services.edit_fields(caller, challenge, stat_key=stat, tag=tag)
            elif switch == "edit":
                services.edit_fields(caller, challenge, description=limited(value))
            else:
                services.edit_fields(caller, challenge, difficulty=value.strip())
        elif "void" in switches:
            body, reason = split_comment(args)
            ref, sep, attempt = body.partition(".")
            if not sep:
                raise ContestError("Usage: +challenge/void #n.<attempt id> [# reason]")
            challenge = services.find_challenge(caller, number(ref))
            services.void_attempt(caller, challenge, number(attempt), reason=reason)
        elif switches & {"once", "close"}:
            challenge = services.find_challenge(caller, number(args), open_only=True)
            if "once" in switches:
                services.set_once(caller, challenge)
            else:
                services.close_challenge(challenge, caller=caller)
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
            raise ContestError("Usage: +challenge; see help +challenge for switches.")
        else:
            room = services.room_for(caller)
            sweep_idle(room=room)
            challenges = Challenge.objects.filter(room=room, status=Challenge.Status.OPEN)
            lines = [
                f"#{c.number} ({c.difficulty}) by {c.set_by_name}{' [once]' if c.once else ''}: {c.description}"
                + (
                    f" [suggested: {c.stat_key}{'/' + c.tag if c.tag else ''}]"
                    if c.stat_key
                    else ""
                )
                for c in challenges
            ]
            self.msg(
                "Open challenges:\n" + "\n".join(lines) if lines else "No open challenges here."
            )


class ContestCmdSet(CmdSet):
    key = "RPContestCmdSet"

    def at_cmdset_creation(self):
        self.add(CmdTest())
        self.add(CmdChallenge())
