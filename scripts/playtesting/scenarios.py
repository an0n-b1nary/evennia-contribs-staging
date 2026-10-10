"""RP acceptance cases over real authenticated, nonsuperuser sessions."""

import json
import re
import traceback

from .client import visible

STATS = ("strength", "endurance", "intellect", "intuition", "presence", "resolve", "agility")
OUTCOMES = {
    "critical_failure",
    "failure",
    "narrow_failure",
    "narrow_success",
    "success",
    "critical_success",
}


def shows_rating(text, display):
    """True if a rating such as `B` or `B ++` appears as its own token in `text`.

    A bare substring test would see the grade `B` inside words like "Blades".
    """
    return re.search(rf"(?<![\w+-]){re.escape(display)}(?![\w+-])", text) is not None


class Suite:
    def __init__(self, session):
        self.session = session
        self.results = []

    def case(self, name, function):
        try:
            function()
        except AssertionError as exc:
            self.results.append(
                {"name": name, "passed": False, "error": str(exc) or traceback.format_exc()}
            )
            return False
        self.results.append({"name": name, "passed": True})
        return True

    def command(self, actor, command, matches=None):
        result = self.session.send(actor, command)
        if matches:
            assert re.search(matches, result["output"], re.I | re.S), (
                f"{actor} {command!r}: expected {matches!r}, received {result['output']!r}"
            )
        assert (
            "Traceback" not in result["output"] and "An untrapped error" not in result["output"]
        ), result
        return result

    def state(self):
        return self.session.snapshot()

    def observer(self, result, actor="bob"):
        return visible(self.session.clients[actor].text(result["cursor"]))

    def prepare(self):
        for actor in ("alice", "bob", "staff"):
            self.session.connect(actor)
        info = self.session.host.evidence
        for actor in ("alice", "bob"):
            identity = json.loads((info.directory / f"identity-{actor}.json").read_text())
            assert identity["permissions"] == ["player"] and identity["character_permissions"] == [
                "player"
            ]
        identity = json.loads((info.directory / "identity-staff.json").read_text())
        assert identity["permissions"] == ["builder"] and not identity["superuser"]
        self.command("alice", "+playtest/state denied", "Only the playtest staff")

    def resources(self):
        before = self.state()
        alice_id = before["actors"]["alice"]["id"]

        def grain(state):
            return sum(
                row["quantity"]
                for row in state["resource_holdings"]
                if row["character_id"] == alice_id and row["resource__key"] == "grain"
            )

        self.command("alice", "+resources", "Resources:.*trickle cap")
        self.command("alice", f"+resources/grant #{alice_id}=grain,3", "Only staff")
        self.command(
            "staff", f"+resources/grant #{alice_id}=grain,3,Live playtest", "Resources updated"
        )
        assert grain(self.state()) >= grain(before) + 3
        self.command("alice", "+gather grain", "Gathering lean: Grain")
        self.command("alice", "+finger", "Gathering.*Grain")
        self.command("staff", "+resources/run dry", "Preview")
        self.command("staff", "+runtime RP_RESOURCES_REVEALED=false", "False")
        try:
            self.command(
                "alice", "+resources", "not available|not found|Could not find|Unknown command"
            )
            self.command("staff", "+resources", "Resources:")
            result = self.command("alice", "+finger")
            assert "Gathering" not in result["output"]
        finally:
            self.command("staff", "+runtime/reset RP_RESOURCES_REVEALED", "True")
        self.command("alice", "+gather/clear", "lean cleared")

    def economy(self):
        state = self.state()
        alice_id = state["actors"]["alice"]["id"]
        bob_id = state["actors"]["bob"]["id"]
        bob_name = self.session.host.credentials["bob"]["name"]

        def purse(snapshot, character_id):
            return next(
                (
                    r["balance"]
                    for r in snapshot["economy_purses"]
                    if r["character_id"] == character_id
                ),
                0,
            )

        def grain(snapshot, character_id):
            return sum(
                r["quantity"]
                for r in snapshot["resource_holdings"]
                if r["character_id"] == character_id and r["resource__key"] == "grain"
            )

        self.command("alice", "+balance", "Purse:")
        self.command("alice", "+economy", "Only staff")
        self.command("staff", f"+economy/credit #{alice_id}=20,Live trade", "Purse updated")
        self.command("staff", f"+resources/grant #{bob_id}=grain,3,Live trade", "Resources updated")
        before = self.state()
        self.command("alice", f"+offer {bob_name}=5 coins for resource:grain:2", "Offer #")
        offer_id = self.state()["economy_offers"][-1]["id"]
        result = self.command("bob", f"+accept {offer_id}", "accepted")
        assert "complete a trade" in self.observer(result, "staff")
        after = self.state()
        assert purse(after, alice_id) == purse(before, alice_id) - 5
        assert purse(after, bob_id) == purse(before, bob_id) + 5
        assert grain(after, alice_id) == grain(before, alice_id) + 2
        assert grain(after, bob_id) == grain(before, bob_id) - 2
        self.command("bob", f"+accept {offer_id}", "no longer open")
        self.command("alice", "+offer Playtest alternate=1 coin", "same account")

        self.command("alice", f"+offer {bob_name}=1 coin", "Offer #")
        offer_id = self.state()["economy_offers"][-1]["id"]
        result = self.command("bob", f"+accept/secret {offer_id}", "accepted")
        assert "complete a trade" not in self.observer(result, "staff")
        self.command("staff", "+runtime RP_ECONOMY_FROZEN=true", "True")
        try:
            self.command("alice", f"+offer {bob_name}=1 coin", "market is closed")
            self.command("alice", "+balance", "Purse:")
        finally:
            self.command("staff", "+runtime/reset RP_ECONOMY_FROZEN", "False")
        self.command("staff", "+runtime RP_ECONOMY_REVEALED=false", "False")
        try:
            self.command(
                "alice", "+balance", "not available|not found|Could not find|Unknown command"
            )
            self.command("staff", "+economy/run dry", "Preview")
        finally:
            self.command("staff", "+runtime/reset RP_ECONOMY_REVEALED", "True")
        before = self.state()
        self.command("staff", "+economy/run", "Batch")
        self.command("staff", "+economy/run", "Batch")
        after = self.state()
        assert len({(r["character_id"], r["week"]) for r in after["economy_ubi"]}) == len(
            after["economy_ubi"]
        )
        self.session.disconnect("alice")
        self.session.connect("alice")
        assert self.state()["economy_purses"] == after["economy_purses"]

    def stalls(self):
        self.command("alice", "+stall/claim Live counter", "Claimed stall")
        self.command("alice", "+gear/make live market cloak=body", "make|create")
        self.command("alice", "+stall/list live market cloak=7", "Listing #")
        state = self.state()
        listing = state["economy_listings"][-1]
        store = state["economy_stalls"][-1]
        self.command("alice", f"+buy {listing['id']}", "same account")
        self.command("bob", "+browse", "live market cloak")
        self.command("bob", "+market cloak", "Live counter")
        self.command("staff", "+runtime RP_ECONOMY_FROZEN=true", "True")
        try:
            self.command("bob", f"+buy {listing['id']}", "market is closed")
        finally:
            self.command("staff", "+runtime/reset RP_ECONOMY_FROZEN", "False")
        self.session.disconnect("alice")
        self.command("bob", f"+buy {listing['id']}", "Bought listing")
        self.command("bob", f"+buy {listing['id']}", "no longer available")
        self.session.connect("alice")
        self.command("bob", "drop live market cloak", "drop")
        self.command("bob", "get live market cloak", "pick up|get")
        # Reserved resources return intact when the owner closes the stall.
        self.command("alice", "+stall/list resource:grain:1=3", "Listing #")
        reserved = self.state()["economy_listings"][-1]["id"]
        self.session.host.reload()
        self.command("bob", "+browse", "Grain")
        assert (
            next(row for row in self.state()["economy_listings"] if row["id"] == reserved)["status"]
            == "active"
        )
        self.command("staff", f"+stall/close {store['id']}", "stock returned")
        state = self.state()
        assert all(
            row["status"] != "active"
            for row in state["economy_listings"]
            if row["storefront_id"] == store["id"]
        )
        assert (
            next(row for row in state["economy_stalls"] if row["id"] == store["id"])["status"]
            == "closed"
        )

    def crafting(self):
        state = self.state()
        alice_id = state["actors"]["alice"]["id"]
        self.command(
            "staff", f"+resources/grant #{alice_id}=timber,20,Live crafting", "Resources updated"
        )
        self.command(
            "staff", f"+resources/grant #{alice_id}=ember,2,Live crafting", "Resources updated"
        )
        self.command("staff", f"+economy/credit #{alice_id}=500,Live crafting", "Purse updated")
        self.command("alice", "+workshop/catalog", "Weaver.*Scribe|Scribe.*Weaver")
        self.command("alice", "+workshop/unlock weaving=timber:3", "Unlocked Weaver")
        self.command("alice", "+craft/new weaving/wearable = live crafted cloak", "draft saved")
        self.command("alice", "+craft/desc = A cloak made for the live market.", "draft saved")
        self.command("alice", "+craft/line = a bright woven cloak", "draft saved")
        self.command("alice", "+craft/aura = soft ember sparks", "draft saved")
        self.command("alice", "+craft/slot = body", "draft saved")
        self.command("alice", "+craft/resources = timber:1,ember:1", "draft saved")
        before = self.state()
        self.command("alice", "+craft", "Cost:.*1 materials.*1 essences")
        self.session.host.reload()
        self.command("alice", "+craft", "Draft: live crafted cloak")
        assert self.state()["crafts"] == before["crafts"]
        self.command("staff", "+runtime RP_CRAFTING_FROZEN=true", "True")
        try:
            self.command("alice", "+craft/finish", "Crafting is paused")
        finally:
            self.command("staff", "+runtime/reset RP_CRAFTING_FROZEN", "False")
        self.command("alice", "+craft/finish", "You craft live crafted cloak")
        self.command("alice", "+craft/finish", "Start a draft")
        self.command("alice", "+wear live crafted cloak", "put on")
        self.command("alice", "+worn", "soft ember sparks")
        self.command("alice", "+remove live crafted cloak", "take off")
        self.command("alice", "+gear/info live crafted cloak", "Craft hallmark:.*Weaver")
        self.command("alice", "+stall/claim Crafted counter", "Claimed stall")
        self.command("alice", "+stall/list live crafted cloak=8", "Listing #")
        self.command("bob", "+market weaver", "Crafted counter")
        listing = self.state()["economy_listings"][-1]
        self.session.disconnect("alice")
        self.command("bob", f"+buy {listing['id']}", "Bought listing")
        self.command("bob", "+market weaver", "No matching open stalls")
        self.session.connect("alice")
        self.command("bob", "+gear/info live crafted cloak", "Craft hallmark:.*Weaver")
        self.command("bob", "+gear/desc live crafted cloak = Forged", "Only its maker|fixed now")
        self.command("alice", "+workshop/unlock writing=timber:6", "Unlocked Scribe")
        self.command("alice", "+craft/new writing/readable = live field notes", "draft saved")
        self.command("alice", "+craft/desc = A bound field notebook.", "draft saved")
        self.command("alice", "+craft/text = A record of the market road.", "draft saved")
        self.command("alice", "+craft/resources = timber:1", "draft saved")
        self.command("alice", "+craft/finish", "You craft live field notes")
        self.command("alice", "read live field notes", "record of the market road")
        self.command("staff", "+crafting/review", "live field notes")
        self.command("alice", "+workshop/abandon weaving", "not refunded")
        self.command("alice", "+workshop", "1/5 active niches")
        self.command("staff", "+runtime RP_CRAFTING_REVEALED=false", "False")
        try:
            self.command(
                "alice", "+workshop", "not available|not found|Could not find|Unknown command"
            )
            self.command("staff", "+crafting/review", "Recent crafts")
        finally:
            self.command("staff", "+runtime/reset RP_CRAFTING_REVEALED", "True")
        self.command("alice", "+stall/close", "stock returned")
        assert len(self.state()["crafts"]) == len(before["crafts"]) + 2

    def events(self):
        alice_id = self.state()["actors"]["alice"]["id"]
        for resource in ("grain", "ember"):
            self.command(
                "staff",
                f"+resources/grant #{alice_id}={resource},20,Live EVENT",
                "Resources updated",
            )
        self.command("staff", f"+economy/credit #{alice_id}=1000,Live EVENT", "Purse updated")
        self.command("alice", "+workshop/unlock cooking=grain:6", "Unlocked Cook")
        self.command("alice", "+workshop/unlock illusions=ember:9", "Unlocked Illusionist")
        for niche, kind, resource, name, beat in (
            (
                "cooking",
                "consumable",
                "grain",
                "live spice cake",
                "Warm spice fills the laboratory.",
            ),
            ("illusions", "broadcast", "ember", "live muted globe", "Muted golden sparks bloom."),
            (
                "illusions",
                "broadcast",
                "ember",
                "live bright globe",
                "Visible golden sparks bloom.",
            ),
        ):
            self.command("alice", f"+craft/new {niche}/{kind}={name}", "draft saved")
            self.command("alice", "+craft/desc = A small live demonstration.", "draft saved")
            self.command("alice", f"+craft/beat = {beat}", "draft saved")
            self.command("alice", f"+craft/resources = {resource}:1", "draft saved")
            self.command("alice", "+craft/finish", "You craft")
        self.command("bob", "+ambient/mute", "muted")
        result = self.command("alice", "use live spice cake", "You use")
        assert "<EVENT> Warm spice" in self.observer(result)
        self.command("bob", "gallery", "ambient gallery")
        self.command("staff", "+runtime RP_CRAFTING_EVENT_ROOM_COOLDOWN=1", "1")
        self.session.host.reload()
        result = self.command("alice", "use live muted globe", "You use")
        assert "Muted golden sparks" not in self.observer(result)
        self.command("staff", "+runtime RP_CRAFTING_EVENT_ROOM_COOLDOWN=300", "300")
        self.session.host.reload()
        self.command("alice", "use live bright globe", "Wait a moment")
        assert len(self.state()["event_uses"]) == 2
        self.command("bob", "+ambient/unmute", "enabled")
        self.command("staff", "+runtime RP_CRAFTING_EVENT_ROOM_COOLDOWN=1", "1")
        result = self.command("alice", "use live bright globe", "You use")
        assert "<EVENT> Visible golden sparks" in self.observer(result)
        self.command("alice", "use live bright globe", "Could not find|not find")
        assert len(self.state()["event_uses"]) == 3
        self.command("bob", "laboratory", "laboratory")
        self.command("staff", "+runtime/reset RP_CRAFTING_EVENT_ROOM_COOLDOWN", "30")

    def sheets(self):
        self.command("alice", "+stats presence=potato", "unknown|invalid|expected|grade")
        self.command("alice", "+stats/finalize", "Not yet")
        for stat in STATS[:2]:
            self.command("alice", f"+stats {stat}=S", "now S")
        self.command("alice", "+stats intellect=S", "points|budget|allocation")
        assert self.state()["actors"]["alice"]["stats"]["intellect"] is None
        for actor in ("alice", "bob"):
            for stat in STATS:
                self.command(actor, f"+stats {stat}=B", "now B")
            self.command(actor, "+stats/finalize", "Sheet finalized")
            self.command(actor, "+stats presence=A", "stats are final")
        state = self.state()
        for actor in ("alice", "bob"):
            assert state["actors"][actor]["status"] == "finalized"
            assert set(state["actors"][actor]["stats"].values()) == {"B"}

    def pips(self):
        self.command("alice", "+pips/set presence=6", "at most")
        self.command("alice", "+pips/weakness endurance=6", "at most")
        self.command("alice", "+pips/set presence=2", "Presence")
        self.command("alice", "+pips/weakness endurance=1", "Endurance")
        state = self.state()["actors"]["alice"]
        assert state["stats"]["presence"] == "B ++"
        assert state["stats"]["endurance"] == "B -"
        self.command("alice", "+pips/set resolve=4", "Resolve")
        self.command("alice", "+pips/set intellect=5", "budget|pips|remaining")
        assert self.state()["actors"]["alice"]["stats"]["intellect"] == "B"

    def purchases(self):
        self.command("alice", "+spend/ability proficiency: performance", "You learn")
        self.command("alice", "+abilities/unequip proficiency: performance", "no longer equipped")
        self.command("alice", "+abilities/equip proficiency: performance", "now equipped")
        self.command("alice", "+spend/ability combat focus: blades", "You learn")
        state = self.state()
        assert float(state["actors"]["alice"]["allowance"]) == 4
        owned = state["actors"]["alice"]["abilities"]
        assert all(row["equipped"] for row in owned) and len(owned) == 2
        assert not [
            row for row in state["spends"] if row["character_id"] == state["actors"]["alice"]["id"]
        ]

    def mixed_funding(self):
        self.command("staff", "+chargen/allowance pt-bob=1", "allowance")
        self.command("staff", "+xp/grant pt-bob=10:Live playtest", "10")
        self.command("bob", "+spend/ability proficiency: performance", "You learn")
        state = self.state()
        bob = state["actors"]["bob"]["id"]
        purchase = [
            row
            for row in state["transactions"]
            if row["character_id"] == bob and row["kind"] == "acquire"
        ]
        assert len(purchase) == 1, purchase
        assert float(purchase[0]["allowance_amount"]) == 1 and float(purchase[0]["xp_amount"]) == 2
        for level in (2, 3):
            self.command("bob", "+upgrade proficiency: performance", f"level {level}")
        before = self.state()
        self.command("bob", "+upgrade proficiency: performance", "need|enough|insufficient")
        after = self.state()
        for key in ("transactions", "spends", "xp"):
            assert before[key] == after[key], f"Failed purchase changed {key}"
        assert before["actors"]["bob"] == after["actors"]["bob"], (
            "Failed purchase changed Bob's build"
        )
        self.command(
            "staff", "+chargen/revoke/refund pt-bob/proficiency: performance", "refund|revok"
        )
        state = self.state()
        assert not state["actors"]["bob"]["abilities"]
        assert float(state["actors"]["bob"]["allowance"]) == 1
        assert (
            float(next(row for row in state["xp"] if row["character_id"] == bob)["current_balance"])
            == 10
        )
        assert all(row["refunded_at"] for row in state["spends"] if row["character_id"] == bob)

    def locks(self):
        self.command("alice", "ooc Choosing an approach.", "Choosing an approach")
        assert not self.state()["actors"]["alice"]["locked"]
        self.command("alice", "pose studies the gap.", "studies the gap")
        assert self.state()["actors"]["alice"]["locked"]
        self.command("alice", "+pips/set presence=1", "locked")
        result = self.command("alice", "+unlock", "unlock")
        assert "unlocks" in self.observer(result)
        self.command("alice", "+pips/set presence=1", "Presence")
        self.command("alice", "+pips/set presence=2", "Presence")
        self.command("alice", "pose commits to the leap.", "commits to the leap")
        assert self.state()["actors"]["alice"]["locked"]
        self.command("alice", "+unlock", "unlock")

    def scene_check(self):
        self.command("alice", "+scene/open Live Telnet laboratory", "opened|created|Scene #")
        self.command("alice", "+test/set A=Presence/Performance~Hold the audience", "challenge #1")
        before = self.state()
        result = self.command("alice", "+test #1=Presence/Performance", "Narrow Success")
        public = self.observer(result)
        assert "Narrow Success" in public
        for hidden in ("B ++", "55.2", '"roll"', "noise", "actor_score"):
            assert hidden not in public, f"Private rating leaked: {public}"
        state = self.state()
        record = state["checks"][-1]
        assert record["outcome_key"] == "narrow_success" and record["rating_display"] == "B ++", (
            record
        )
        logs = [
            row for row in state["logs"] if row["id"] not in {old["id"] for old in before["logs"]}
        ]
        assert len(logs) == 1 and logs[0]["log_type"] == "system", logs
        assert "B ++" not in logs[0]["content"]
        assert before["sessions"] == state["sessions"], "A check earned RP pose credit"
        assert before["earn_count"] == state["earn_count"], "A check earned XP"

    def challenges(self):
        self.command("alice", "+test Presence/Performance", "on #1")
        self.command("bob", "+test/set B~Cross the chasm", "challenge #2")
        self.command("alice", "+test #2=Intellect/Ritual", "on #2")
        assert not self.state()["checks"][-1]["alternative"]
        self.command("alice", "+test #1=Agility/Blades", "alternative approach")
        record = self.state()["checks"][-1]
        assert record["tag"] == "blades" and record["alternative"]
        assert "Combat Focus" in str(record["detail"]), record
        self.command("alice", "+test #1=Agility/Blades", "attempt 4")
        # An exact suggested approach binds; multiple matching suggestions are ambiguous.
        self.command("bob", "+test/set B=Presence/Performance~A second audience", "challenge #3")
        self.command("alice", "+test Presence/Performance", "tests Presence")
        assert self.state()["checks"][-1]["challenge_id"] is None
        self.command("alice", "+test #3=Presence/Performance", "on #3")

    def management(self):
        self.command("bob", "+test/set/once B=Intellect~One careful attempt", "challenge #4")
        self.command("alice", "+test #4=Intellect", "on #4")
        record = self.state()["checks"][-1]
        self.command("alice", "+test #4=Intellect", "only one attempt")
        assert self.state()["checks"][-1]["id"] == record["id"]
        self.command("alice", "+test/edit #4=A=Intellect~Not authorized", "setter or staff")
        self.command("alice", f"+test/void #4/{record['id']}~Not authorized", "setter or staff")
        self.command("bob", "+test/edit #4=A=Intellect~Edited attempt", "edits challenge")
        self.command("bob", f"+test/void #4/{record['id']}~Retry permitted", "void")
        self.command("alice", "+test #4=Intellect", "attempt 2")
        state = self.state()
        assert next(row for row in state["checks"] if row["id"] == record["id"])["voided_at"]
        assert state["checks"][-1]["attempt_no"] == 2
        self.command("staff", "+test/once #3", "once")
        self.command("alice", "+test/history #4", f"Attempt {record['id']}")
        self.command("alice", "+test/review", "Only staff")
        self.command("staff", "+test/review #4", '"resolution"|"roll"')
        self.command("alice", "+sheet", "Presence")
        self.command("bob", "+sheet pt-alice", "only see your own")
        self.command("staff", "+sheet pt-alice", "Presence")

    def adversarial(self):
        payload = "{actor} $You() |rCOLOR|n braces {unknown} <script>literal</script>"
        result = self.command(
            "alice", f"+test #2=Intellect~{payload}", r"\{actor\}.*\$You\(\).*COLOR.*\{unknown\}"
        )
        assert "{actor}" in self.observer(result) and "$You()" in self.observer(result)
        assert self.state()["checks"][-1]["comment"] == payload

    def tracker(self):
        for index in range(3):
            for actor in ("alice", "bob"):
                self.command(
                    actor,
                    f"pose shares live laboratory observation {index}.",
                    "laboratory observation",
                )
        state = self.state()
        for actor in ("alice", "bob"):
            actor_id = state["actors"][actor]["id"]
            assert any(
                row["character_id"] == actor_id and row["status"] == "active"
                for row in state["sessions"]
            )
        self.command("alice", "+test/set C~Alice session challenge", "challenge #5")
        self.command("bob", "+test/set C~Bob session challenge", "challenge #6")
        self.command("alice", "+activity/end", "ended|Ending")
        state = self.state()
        assert not state["actors"]["alice"]["locked"]
        assert state["actors"]["bob"]["locked"]
        challenges = {row["number"]: row for row in state["challenges"]}
        assert challenges[5]["closed_reason"] == "session_end"
        assert challenges[6]["status"] == "open"
        self.command("alice", "+scene/close", "closed")
        state = self.state()
        assert all(row["status"] == "closed" for row in state["challenges"])

    def reconnect(self):
        before = self.state()
        self.session.disconnect("alice")
        self.session.connect("alice")
        self.command("alice", "+sheet", "Presence")
        after = self.state()
        for key in ("status", "stats", "abilities", "allowance"):
            assert before["actors"]["alice"][key] == after["actors"]["alice"][key], key
        assert before["checks"] == after["checks"]

    def normal_rng(self):
        for command in (
            "+pips/set presence=2",
            "+spend/ability proficiency: performance",
            "+spend/ability combat focus: blades",
        ):
            self.command("alice", command)
        for approach in ("Presence/Performance", "Agility/Blades"):
            result = self.command("alice", f"+test {approach}", "Success|Failure")
            state = self.state()
            record = state["checks"][-1]
            assert record["outcome_key"] in OUTCOMES, record
            assert record["detail"]["outcome"]["label"] in self.observer(result)
            assert not shows_rating(self.observer(result), record["rating_display"]), record
        assert len(self.state()["checks"]) == 2


def run_rp(session, smoke=False):
    suite = Suite(session)
    cases = [
        ("ordinary login, staff role and probe authorization", suite.prepare),
        ("resource holdings, lean, staff grants and runtime reveal", suite.resources),
        ("atomic economy trade, same-account rule, freeze and reveal", suite.economy),
        ("reserved stall stock, offline purchase, freeze and stock recovery", suite.stalls),
        ("invested niches, persistent crafts, hallmarks and offline crafted sale", suite.crafting),
        ("consumed EVENTs, adjacent Broadcast mute and durable audience limits", suite.events),
        ("draft validation, allocation and finalization", suite.sheets),
    ]
    if smoke:
        cases += [("normal RNG domain and style checks", suite.normal_rng)]
    else:
        cases += [
            ("Pip policy", suite.pips),
            ("allowance purchases and loadout", suite.purchases),
            ("mixed allowance/XP, upgrade rollback and refund", suite.mixed_funding),
            ("OOC/IC locks and announced manual unlock", suite.locks),
            ("deterministic check, room privacy and scene SYSTEM log", suite.scene_check),
            ("player challenges, binding, alternatives and retries", suite.challenges),
            ("once, edit, retained void IDs and sheet/review authorization", suite.management),
            ("literal braces, FuncParser, color and HTML comments", suite.adversarial),
            ("real RP session end and scene-close expiry", suite.tracker),
            ("reconnect preserves sheet and audit", suite.reconnect),
        ]
    for name, function in cases:
        if not suite.case(name, function):
            break  # Subsequent cases depend on this state; never report them as passing.
    return suite.results
