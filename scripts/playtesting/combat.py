"""Ordinary authenticated players exercise combat through live commands."""

import re

from .scenarios import Suite


class CombatSuite(Suite):
    def consent_and_cancellation(self):
        self.command("alice", "+combat/setup Live combat acceptance", "set up combat")
        self.command("alice", "+combat/join one", "joined side one")
        self.command("alice", "+combat/attack pt-bob=balanced", "invite|invitation")
        self.command("bob", "+combat/refuse", "refus|declin")
        self.command("bob", "+combat", "Vitality")
        self.command("bob", "+combat/join two", "joined side two")
        self.command("alice", "+combat/attack pt-bob=balanced;rps=subtle")
        queue = self.command("bob", "+combat")["output"]
        token = re.search(r"Incoming ([0-9.]+:[0-9]+):", queue).group(1)
        self.command("bob", "+combat/odds " + token, "neutral RPS estimates")
        self.command("bob", "+combat/cancel " + token, "cancel")
        self.command("alice", "+combat", "turns 0/4")

    def reaction_build_lock_and_reload(self):
        self.command("alice", "+combat/attack pt-bob=heavy;rps=penetrating")
        queue = self.command("bob", "+combat")["output"]
        token = re.search(r"Incoming ([0-9.]+:[0-9]+):", queue).group(1)
        self.session.host.reload()
        self.command("bob", "+combat", re.escape(token))
        self.command("bob", "+combat/react " + token + "=resist", "resist")
        self.command("bob", "+combat/cancel " + token, "unaccepted|stale|match")
        self.command("alice", "+combat/result " + token.split(":")[0], "penetrating")
        self.command("alice", "+unlock", "unlock|already|aren't locked")
        self.command("alice", "+pips/set strength=1", "combat build is frozen")
        self.command("alice", "+combat/unlock Agreed correction", "unlock")
        self.command("alice", "+unlock")
        self.command("alice", "+pips/set strength=1", "Strength")
        self.command("alice", "+combat/relock Agreed correction", "relock")
        self.command("alice", "+combat/posed", "posed")
        self.command("bob", "+combat/posed", "posed")

    def automation_storytelling_and_fade(self):
        self.command("bob", "+combat/auto on", "auto on")
        self.command("alice", '+tactics/save Accessible={"rps_appetite":"bold"}', "Active Tactics")
        self.command("alice", "+combat/act", "Auto-Act")
        self.command("alice", "+combat", "turns 2/4")
        self.command("bob", "+combatstory/requestcap pt-alice=3;OOC agreement", "requestcap")
        self.command("alice", "+combat/accept", "accepted request")
        self.command("alice", "+combat/fade", "fade")
        self.command("alice", "+combat/join one", "joined")
        self.command("alice", "+combat", "turns 2/3")
        self.command("alice", "+combatstory/pause Discuss outcome", "pause")
        self.command("alice", "+combat/act", "paused")
        self.command("bob", "+combatstory/end Agreed outcome", "Ending needs agreement")
        self.command("alice", "+combat/accept", "accepted request")
        self.command("alice", "+combat", "ended")

    def consensual_return(self):
        self.command("alice", "+combat/setup Agreed return rehearsal", "set up combat")
        self.command("alice", "+combat/join one", "joined")
        self.command("bob", "+combat/join two", "joined")
        self.command("bob", "+combat/withdraw", "withdraw")
        self.command("bob", "+combat/join two", "request your return")
        self.command("alice", "+combatstory/requestreturn pt-bob=25;Agreed return", "requestreturn")
        self.command("bob", "+combat", "return you to the fight at 25 Vitality")
        self.command("bob", "+combat/decline", "declined request")
        self.command("bob", "+combat/accept", "no pending storyteller requests")
        self.command("alice", "+combatstory/requestreturn pt-bob=25;Agreed return", "requestreturn")
        self.command("bob", "+combat/accept", "accepted request")
        self.command("bob", "+combat", "25/100 Vitality; turns 0/4")
        self.command("alice", "+combatstory/end Agreed outcome", "Ending needs agreement")
        self.command("bob", "+combat/accept", "accepted request")

    def revival_and_recovery(self):
        stats = ",".join(
            f"{stat}:B"
            for stat in (
                "strength",
                "endurance",
                "intellect",
                "intuition",
                "presence",
                "resolve",
                "agility",
            )
        )
        mend = '{"key":"mend","name":"Mend","action":"assist","effects":["heal"]}'
        self.command("alice", "+npc/create Sparring Post =template", "Created NPC blueprint")
        self.command("alice", f"+npc/stats Sparring Post ={stats}", "updated")
        self.command("alice", "+combat/setup Revival rehearsal", "set up combat")
        self.command("alice", "+combat/join one", "joined")
        self.command("bob", "+combat/join one", "joined")
        self.command("alice", "+combatstory/template Sparring Post=two", "Sparring Post")
        self.command("bob", "+combatstory/vitality pt-alice=0;Agreed knockdown", "vitality")
        self.command("alice", "+combat/accept", "accepted request")
        self.command("alice", "+combat/act", "incapacitated")
        self.command("bob", "+combat/improv pt-alice=" + mend, r"\d+\.\d+")
        self.command("alice", "+combat", "Revival offer")
        self.command("alice", "+combat/decline", "declined .*revival")
        self.command("alice", "+combat", "0/100 Vitality")
        self.command("alice", "+combat/revive accept", "revive accept")
        self.command("bob", "+combat/improv pt-alice=" + mend, r"\d+\.\d+")
        self.command("alice", "+combat", "You are recovering")
        self.command("alice", "+combat/attack Sparring Post=balanced", "recover")
        self.command("alice", "+combat/recover", "recovery action")
        self.command("alice", "+combat/posed", "posed")
        self.command("bob", "+combat/posed", "posed")
        self.command("alice", "+combatstory/end Agreed outcome", "Ending needs agreement")
        self.command("bob", "+combat/accept", "accepted request")


def run_combat(session):
    suite = CombatSuite(session)
    cases = [
        ("ordinary player login and permissions", suite.prepare),
        ("playable sheets through normal chargen", suite.sheets),
        ("explicit consent, refusal and pre-reaction cancellation", suite.consent_and_cancellation),
        (
            "reload, reactions, result recovery and announced build correction",
            suite.reaction_build_lock_and_reload,
        ),
        (
            "opt-in automation, consented storyteller requests, reduced cap and retained Fade",
            suite.automation_storytelling_and_fade,
        ),
        (
            "storyteller-requested return with personal refusal and acceptance",
            suite.consensual_return,
        ),
        (
            "consented revival by an ally, standing acceptance and one recovery action",
            suite.revival_and_recovery,
        ),
    ]
    for name, function in cases:
        if not suite.case(name, function):
            break
    return suite.results
