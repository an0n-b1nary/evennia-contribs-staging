# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent Boss Check drafts and verdict-bound confirmation previews."""

from evennia.utils.dbserialize import deserialize
from evennia_rp_combat import services as combat
from evennia_rp_combat.command_syntax import CombatCommand
from evennia_rp_combat.data import CombatError

from . import boss_services as services

DRAFT = "boss_check_draft"
PREVIEWS = "boss_check_previews"
CATEGORY = "rp_party"
FIELDS = ("type", "difficulty", "value", "requirement", "hint", "approaches", "roll")


class CmdBossCheck(CombatCommand):
    """Offer manual Party challenges through a draft, then resolve a preview token.

    +bosscheck                         Inspect status and your draft
    +bosscheck/new <parties>            Begin a draft for comma-separated Parties
    +bosscheck/type <type>              Tank, DPS, Support, Pressure, Special, Contest
    +bosscheck/difficulty <difficulty>  Easy, Balanced or Hard
    +bosscheck/value <value>            Override the type's threshold
    +bosscheck/requirement <text>       Special requirement
    +bosscheck/hint <text>              Special hint
    +bosscheck/approaches <stats>       Comma-separated stat or stat/tag approaches
    +bosscheck/rollrating <rating>      Contest difficulty rating
    +bosscheck/finish                   Validate and issue the draft
    +bosscheck/discard                  Discard your unissued draft
    +bosscheck/preview <id>[=pass]       Preview consequences (pass/fail for Special)
    +bosscheck/resolve <id>=<token> # <reason>
    +bosscheck/withdraw <id> # <reason>  Cancel only your participation
    +bosscheck/cancel <id> # <reason>    Cancel your Party's pending Check
    +bosscheck/roll <id>=<stat>[/<tag>]  One free bound Contest response
    +bosscheck/allow <id>/<member>=<stat>[/<tag>]

    Boss Mode x2+ and clear queues are required to issue. No actions are
    spent by issuance or response rolls. Pending cancellation is free.
    Preview binds the Special verdict into its token; changes require a new preview.
    """

    key = "+bosscheck"
    switch_options = (
        "new",
        "type",
        "difficulty",
        "value",
        "requirement",
        "hint",
        "approaches",
        "rollrating",
        "finish",
        "discard",
        "preview",
        "resolve",
        "withdraw",
        "cancel",
        "roll",
        "allow",
    )

    def run(self):
        actor, subject = self.caller, self.subject
        op = self.switches[0] if self.switches else ""
        from .services import require

        require(actor, progress=op not in ("", "preview", "discard", "cancel", "withdraw"))
        attrs = subject.attributes
        draft = deserialize(attrs.get(DRAFT, category=CATEGORY, default={}))
        if not op:
            if self.args.strip():
                raise CombatError("Start a draft with +bosscheck/new <parties>.")
            from .services import render

            self.msg(render(actor, subject=subject))
            if draft:
                self.msg(
                    f"Boss Check draft: {draft['type']} ({draft['difficulty']}) for {', '.join(draft['parties'])}. Use +bosscheck/finish to issue."
                )
            return
        if op == "new":
            if draft:
                raise CombatError("Finish or discard your current Boss Check draft first.")
            parties = [p.strip() for p in self.args.split(",") if p.strip()]
            if not parties:
                raise CombatError("Name at least one Party.")
            draft = {"parties": parties, "type": "tank", "difficulty": "balanced"}
        elif op == "discard":
            attrs.remove(DRAFT, category=CATEGORY)
            self.msg("Boss Check draft discarded.")
            return
        elif op in (*FIELDS, "rollrating") and op != "roll":
            if not draft:
                raise CombatError("Start with +bosscheck/new <parties>.")
            draft["roll" if op == "rollrating" else op] = self.args.strip()
        elif op == "finish":
            if not draft:
                raise CombatError("Start with +bosscheck/new <parties>.")
            result = services.issue(
                actor,
                list(draft["parties"]),
                draft["type"].lower(),
                subject=subject,
                difficulty=draft["difficulty"].lower(),
                options={k: draft[k] for k in ("value", "requirement", "hint") if k in draft},
                approaches=tuple(
                    p.strip() for p in draft.get("approaches", "").split(",") if p.strip()
                ),
                roll_difficulty=draft.get("roll"),
            )
            attrs.remove(DRAFT, category=CATEGORY)
            self.msg(f"Boss Checks issued: {', '.join(result)}.")
            return
        elif op == "preview":
            verdict = None
            if self.rhs is not None:
                if self.rhs.strip().lower() not in ("pass", "fail"):
                    raise CombatError("Choose pass or fail for a Special preview.")
                verdict = self.rhs.strip().lower() == "pass"
            ident = self.lhs.strip()
            view = services.preview(actor, ident, subject=subject, verdict=verdict)
            previews = dict(attrs.get(PREVIEWS, category=CATEGORY, default={}))
            previews[ident] = {"token": view["token"], "verdict": verdict}
            attrs.add(PREVIEWS, previews, category=CATEGORY)
            self.msg("\n".join(combat.plain(line, 1000) for line in view["lines"]))
            return
        elif op == "resolve":
            ident = self.lhs.strip()
            token, _, reason = (self.rhs or "").partition(" # ")
            saved = attrs.get(PREVIEWS, category=CATEGORY, default={}).get(ident)
            if not saved or saved["token"] != token:
                raise CombatError("Preview first, then resolve with the current token.")
            result = services.resolve(
                actor,
                ident,
                token,
                subject=subject,
                verdict=saved["verdict"],
                acknowledgment=reason,
            )
            self.msg(f"Check {ident}: {'passed' if result['passed'] else 'failed'}.")
            return
        elif op in ("cancel", "withdraw"):
            ident, _, reason = self.args.partition(" # ")
            result = services.cancel(
                actor, ident.strip(), subject=subject, individual=op == "withdraw", reason=reason
            )
            self.msg(f"Boss Check {op}: {result}.")
            return
        elif op == "roll":
            result = services.roll(
                actor, self.lhs.strip(), (self.rhs or "").strip(), subject=subject
            )
            self.msg(f"Contest response: {'pass' if result['success'] else 'fail'}.")
            return
        elif op == "allow":
            ident, sep, name = self.lhs.partition("/")
            if not sep or not self.rhs:
                raise CombatError("Use +bosscheck/allow <id>/<member>=<stat>.")
            member = actor.search(name.strip())
            if member:
                result = services.allow(
                    actor, ident.strip(), member, self.rhs.strip(), subject=subject
                )
                self.msg(f"Boss Check allow: {result}.")
            return
        else:
            raise CombatError("See help +bosscheck.")
        attrs.add(DRAFT, draft, category=CATEGORY)
        self.msg("Boss Check draft saved. Use +bosscheck/finish to issue.")
