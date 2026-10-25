# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Deterministic fight state machine, independent of Evennia objects.

The coordinator supplies authorized identities, immutable builds and draws.
An operation mutates a private copy under one database transaction. Failed
operations discard that copy, including reservations and accepted reactions.
"""

from copy import deepcopy
from fractions import Fraction as F

from . import arithmetic as math
from . import partners
from .data import TIERS, Build, CombatError, Move, ReactionView
from .modifiers import bonus as passive
from .modifiers import move_cost, rps_shift, rules
from .state import SCHEMA

DOMAIN_ACTIONS = {
    "grapple": ("attack", "spell"),
    "slip_inside": ("overpower",),
    "ambush": ("attack", "spell"),
    "endure": ("resist",),
    "pilfer": ("attack", "spell"),
    "treat": ("assist",),
    "envenom": ("attack", "spell"),
    "ward": ("assist",),
    "analyze": ("attack", "spell", "assist", "dispirit"),
    "read": ("evade", "resist", "overpower"),
    "pinpoint": ("attack", "spell"),
    "exhort": ("assist",),
    "encore": ("assist",),
    "provoke": ("dispirit",),
    "beguile": ("dispirit",),
    "misdirect": ("dispirit",),
}


def new_state():
    return partners.upgrade_sections(
        {
            "schema": SCHEMA,
            "partners": {},
            "epoch": 1,
            "next_exchange": 1,
            "participants": {},
            "exchanges": {},
            "denominators": {},
            "started": False,
            "paused": False,
            # Why the fight is paused: storyteller, faded (nobody active) or
            # reconciliation (after staff rollback; staff resume).
            "pause_reason": "",
            "ended": False,
            "imbalance": "",
            "templates": {},
            "invitations": {},
            "next_request": 1,
            "end_proposal": None,
            "effect_results": {},
        }
    )


def participating(row):
    """Saved mechanical eligibility, independent of live connection presence.

    A personal cap limits outgoing actions, not defensive participation.
    A revived participant awaiting their recovery action is treated as
    incapacitated: not participating, targetable or able to Cover.
    """
    return (
        row["status"] == "active"
        and row["hp"] > 0
        and not row.get("return_required")
        and not row.get("recovering")
        and not row["correction"]
        and not row.get("absent")
    )


def participant(state, ident):
    try:
        return state["participants"][str(ident)]
    except KeyError:
        raise CombatError("Join this fight explicitly first.") from None


def active(state, ident):
    row = participant(state, ident)
    if row["status"] != "active" or row["hp"] <= 0 or row.get("return_required"):
        raise CombatError("That participant is Faded, withdrawn or incapacitated.")
    if row.get("recovering"):
        raise CombatError(f"{row['name']} is recovering: they take +pass before anything else.")
    if row["correction"]:
        raise CombatError("Relock the corrected build before combat progress.")
    if row.get("absent"):
        raise CombatError(
            "That participant is absent; finish committed reactions or seek staff recovery."
        )
    return row


def progress(state):
    if state["ended"]:
        raise CombatError("This fight has ended.")
    if state["paused"]:
        raise CombatError("This fight is paused.")


def join(state, ident, name, side, build, *, turn_limit=4, boss=1, auto=False, npc=False):
    """Enroll, or restore a Faded participant exactly as they left.

    A rejoin ignores ``side``, ``build``, ``boss`` and ``turn_limit``: the
    retained row, including the build frozen for this fight, is restored.
    """
    if state["ended"]:
        raise CombatError("This fight has ended.")
    key = str(ident)
    if key in state["participants"]:
        row = participant(state, key)
        if row["status"] == "withdrawn":
            raise CombatError("A storyteller must request your return; accept it explicitly.")
        if row["status"] != "faded":
            raise CombatError("You already joined; withdrawn participants cannot rejoin.")
        row["status"] = "active"
        row.pop("absent", None)
        # Restore the exact retained state, including its frozen build.
        row["exposure"] += row["hp"] - row.pop("faded_hp", row["hp"])
        return row
    if (
        type(boss) is not int
        or not 1 <= boss <= 10
        or type(turn_limit) is not int
        or not 1 <= turn_limit <= 20
    ):
        raise CombatError("Boss multiplier must be 1..10 and personal Turn Limit 1..20.")
    if build is None:
        raise CombatError("No combat build is available to join with.")
    if not side or len(side) > 40:
        raise CombatError("Choose a side name of 1..40 characters.")
    row = {
        "id": key,
        "name": name,
        "side": side,
        "build": build.as_dict(),
        "hp": 100 * boss,
        "max_hp": 100 * boss,
        "reserves": 3,
        "spirit": 0,
        "transcendence": 0,
        "pressure": 0,
        "heals": 0,
        "turns": 0,
        "turn_limit": turn_limit,
        "allowance": boss,
        "actions_left": boss,
        "clock": 0,
        "conditions": {},
        "incoming": [],
        "outgoing": None,
        "pose": False,
        "auto": auto,
        "npc": npc,
        "correction": False,
        "status": "active",
        "exposure": 100 * boss,
        "support_history": {},
        "carry": 0,
        # Storyteller changes awaiting this participant's acceptance.
        "requests": [],
        "recovering": False,
        "revive": "ask",
        "tempo": 0,
        "turn_skip": None,
        "partner_subjects": {},
        "actions_spent": 0,
        "armed": {},
    }
    state["participants"][key] = row
    return row


def opening(state):
    if not state["started"]:
        if len({p["side"] for p in state["participants"].values() if p["status"] == "active"}) < 2:
            raise CombatError("Both sides must have accepted participants before combat starts.")
        for row in state["participants"].values():
            if row["status"] == "active":
                side = row["side"]
                state["denominators"][side] = state["denominators"].get(side, 0) + row["max_hp"]
        state["started"] = True


def assessment(state):
    result = {}
    for side in {p["side"] for p in state["participants"].values()}:
        denominator = state["denominators"].get(side, 0)
        contribution = sum(
            (p.get("faded_hp", p["hp"]) if p["status"] == "faded" else p["hp"]) - p["exposure"]
            for p in state["participants"].values()
            if p["side"] == side
        )
        result[side] = (
            str(1 + F(contribution, denominator))
            if denominator
            else "unrated (no opening participants)"
        )
    return result


def condition(row, name, magnitude, duration=1, source="", *, wardable=True):
    """Named conditions refresh at maximum magnitude, never arbitrary stacks.

    Ward absorbs the next harmful condition from someone else. The costs an
    actor accepts by choosing Assist or Burst pass ``wardable=False``.
    """
    if (
        wardable
        and name
        not in (
            "warded",
            "evade_stance",
            "resist_stance",
            "overpower_stance",
            "endure",
            "slip_inside",
            "analyzed",
            "read",
            "bulwark",
        )
        and row["conditions"].get("warded")
    ):
        del row["conditions"]["warded"]
        return
    old = row["conditions"].get(name, {})
    row["conditions"][name] = {
        "magnitude": max(magnitude, old.get("magnitude", 0)),
        "expires": max(row["clock"] + duration, old.get("expires", 0)),
        "source": source,
    }


def value(row, name):
    return row["conditions"].get(name, {}).get("magnitude", 0)


def exposure(row, build, reaction):
    """Vulnerable and Overextended penalties for one reaction.

    Braced Support keeps Vulnerable off Resist and adds to the others.
    """
    vulnerable = value(row, "vulnerable")
    braced = rules(build).get("braced_support")
    if braced and vulnerable:
        vulnerable = 0 if reaction == "resist" else vulnerable + math.rounded(braced["amount"])
    return vulnerable + value(row, "overextended") + value(row, "staggered")


def extension(build, amount):
    """Overextended added by pressing or a broken chain (Explosive)."""
    factor = rules(build).get("explosive", {}).get("factor", F(1))
    return math.rounded(amount * factor)


def shift(build, exchange):
    """Points the attacker's rules add to this exchange's bet."""
    penalty, bonus = rps_shift(build, exchange["bet"])
    if exchange.get("public_bet"):
        penalty += rules(build).get("calling_the_shot", {}).get("amount", F(0))
    return penalty, bonus


def blood_price(row, build, move, owed):
    """Reserves and Vitality to pay ``owed``; Blood Price covers a shortfall.

    Returns (reserves, missing units, Vitality). Only special moves may pay
    in Vitality, and never down to 0; otherwise a shortfall is refused.
    """
    missing = max(0, owed - row["reserves"])
    rate = math.rounded(rules(build).get("blood_price", {}).get("amount", 0))
    if missing and (not rate or move.kind == "standard"):
        raise CombatError("Insufficient Reserves for that move.")
    return owed - missing, missing, missing * rate


def harm(row, amount, *, half_transcendence=False):
    actual = min(row["hp"], max(0, amount))
    row["hp"] -= actual
    if row["hp"] == 0:
        row["return_required"] = True
    award = min(25, math.rounded(F(5, 4) * actual))
    if half_transcendence:
        award = math.rounded(F(award, 2))
    row["transcendence"] = min(100, row["transcendence"] + award)
    return actual


def heal(row, amount):
    actual = min(row["max_hp"] - row["hp"], max(0, amount))
    row["hp"] += actual
    if actual:
        row["heals"] += 1
    return actual


def change_spirit(row, delta):
    old = row["spirit"]
    row["spirit"] = math.clamp(-1000, 2000, old + delta)
    return row["spirit"] - old


def damage_multiplier(build, element):
    multiplier = F(1)
    for key, tag, _level in build.abilities:
        if element and tag == element:
            if key in ("elemental-resistance", "style-resistance"):
                multiplier *= F(4, 5)
            elif key in ("elemental-vulnerability", "style-vulnerability"):
                multiplier *= F(6, 5)
    return multiplier


def has_domain(build, domain):
    return any(
        key in ("domain-expertise", "proficiency") and tag == domain
        for key, tag, _level in build.abilities
    )


# Effects that only help their user or an ally. Domain Resistance blocks a
# domain effect working against its owner, never one that helps them.
HELPFUL_EFFECTS = ("treat", "ward", "exhort", "encore", "endure")


def resists(build, domain):
    """Whether this frozen build carries Domain Resistance to ``domain``."""
    return bool(domain) and any(
        key == "domain-resistance" and tag == domain for key, tag, _level in build.abilities
    )


def blocks(row, domain, effect):
    return effect not in HELPFUL_EFFECTS and resists(Build.from_dict(row["build"]), domain)


def settle(state):
    """Void unanswered packets against anyone at zero Vitality.

    They can no longer react, so each attacker gets their unexecuted
    reservations back, as when a target Fades. Accepted reactions stay
    committed and resolve with their peers. A voided Burst hit ends the chain
    as though the attacker had stopped.
    """
    voided = True
    while voided:
        voided = False
        for row in list(state["participants"].values()):
            if row["hp"] > 0:
                continue
            for token in list(row["incoming"]):
                exchange = state["exchanges"].get(token.split(":")[0])
                if (
                    token in row["incoming"]
                    and exchange is not None
                    and exchange["phase"] == "waiting"
                    and not exchange.get("revival")
                    and row["id"] not in exchange["reactions"]
                ):
                    attacker = participant(state, exchange["actor"])
                    cancel(state, row["id"], token)
                    state.setdefault("notices", []).append(
                        f"{attacker['name']}'s unanswered attack on {row['name']} was voided "
                        "with a refund: they are incapacitated."
                    )
                    voided = True


@partners.atomic_requests
def declaration(
    state,
    ident,
    targets,
    move,
    draw,
    *,
    bet="",
    burst=False,
    empower=False,
    domain="",
    domain_effects=None,
    waive=False,
    public=False,
    support_allowed=None,
    partner_requests=None,
):
    progress(state)
    domain_effects = domain_effects or {}
    actor = active(state, ident)
    used = action_flags(actor, move, bet, state=state, targets=targets)
    burst = burst or bool(used.get("burst"))
    empower = empower or bool(used.get("empower"))
    public = public or bool(used.get("callshot"))
    waive = waive or bool(used.get("waive"))
    partner_requests = surge_request(used, targets, partner_requests)
    if actor["incoming"]:
        raise CombatError("Resolve or cancel every incoming attack before acting.")
    if actor["outgoing"] or actor["pose"]:
        raise CombatError(
            "Finish your outgoing exchange and acknowledge its RP with +combat/posed."
        )
    if actor["turns"] >= actor["turn_limit"]:
        raise CombatError("Your personal Turn Limit is exhausted.")
    targets = [str(t) for t in targets]
    if not targets or len(set(targets)) != len(targets) or len(targets) > actor["actions_left"]:
        raise CombatError("Choose distinct targets within your remaining action allowance.")
    if burst and (len(targets) != 1 or move.action not in ("attack", "spell")):
        raise CombatError("Burst is a single-target Attack or Spell exchange.")
    if bet not in math.RPS or (bet and move.action not in ("attack", "spell")):
        raise CombatError("RPS bets apply only to Attack or Spell.")
    heals = move.action == "assist" and "heal" in move.effects
    revival = heals and any(revivable(participant(state, t)) for t in targets)
    if revival and len(targets) != 1:
        raise CombatError("A revival Heal names one incapacitated ally.")
    if waive and not revival:
        raise CombatError("Only a Heal reviving an incapacitated ally can waive recovery.")
    for target_id in targets:
        target = participant(state, target_id) if revival else active(state, target_id)
        if (
            target_id == actor["id"]
            or (target["side"] == actor["side"] and move.action != "assist")
            or (target["side"] != actor["side"] and move.action == "assist")
        ):
            raise CombatError("Assist another ally; direct hostile actions at the other side.")
    build = Build.from_dict(actor["build"])
    if move.kind == "signature" and move not in build.moves:
        raise CombatError("That Signature is not in your frozen equipped loadout.")
    if public and (not bet or "calling_the_shot" not in rules(build)):
        raise CombatError("Only Calling the Shot makes an RPS bet public.")
    builtin = (
        move.domain
        if has_domain(build, move.domain)
        and move.action in DOMAIN_ACTIONS.get((domain_effects or {}).get(move.domain), ())
        else ""
    )
    chosen_domain = domain or builtin
    if chosen_domain and (
        chosen_domain not in (domain_effects or {}) or not has_domain(build, chosen_domain)
    ):
        raise CombatError("Equip the matching domain expertise before using its combat effect.")
    if chosen_domain and move.action not in DOMAIN_ACTIONS.get(domain_effects[chosen_domain], ()):
        raise CombatError("That domain effect does not apply to this action.")
    if waive and domain_effects.get(chosen_domain) != "treat":
        raise CombatError("Waiving recovery uses Medicine's Treat on the reviving Heal.")
    cost = move_cost(build, move) + (1 if chosen_domain and chosen_domain != move.domain else 0)
    try:
        reserves, missing, blood = blood_price(actor, build, move, cost * len(targets))
    except CombatError:
        raise CombatError("Insufficient Reserves for every target.") from None
    if empower and actor["transcendence"] < 100:
        raise CombatError("Empower requires 100 Transcendence.")
    strain = 5 * len(targets) if "strain" in move.effects else 0
    if strain and actor["hp"] <= strain:
        raise CombatError("Strain must leave at least 1 Vitality.")
    if blood and actor["hp"] - strain - blood < 1:
        raise CombatError("Blood Price must leave at least 1 Vitality.")
    opening(state)
    ex_id = f"{state['epoch']}.{state['next_exchange']}"
    state["next_exchange"] += 1
    exchange = {
        "id": ex_id,
        "actor": actor["id"],
        "move": move.as_dict(),
        "targets": targets,
        "reactions": {},
        "canceled": [],
        "draw": draw,
        "bet": bet,
        "armed": used,
        "burst": burst,
        "hit": 1,
        "empower": empower,
        "cost": cost,
        "domain": chosen_domain,
        "domain_effect": (domain_effects or {}).get(chosen_domain, ""),
        "domain_used": False,
        "paid_ante": 0,
        "debt": 0,
        "resolved": 0,
        "phase": "waiting",
        "outcomes": [],
        "stance_strengths": [],
        "spirit_changes": [],
        "strain_paid": False,
        "empower_used": False,
        "strain_cost": 5 if "strain" in move.effects else 0,
        "actor_conditions": {k: dict(v) for k, v in actor["conditions"].items()},
        "revival": revival,
        "waive_recovery": bool(waive),
        "public_bet": bool(public),
        "blood": {"units": missing, "rate": blood // missing if missing else 0},
    }
    actor["reserves"] -= reserves
    actor["hp"] -= exchange["strain_cost"] * len(targets) + blood
    exchange["strain_paid"] = True
    if empower:
        actor["transcendence"] -= 100
    if burst:
        before = actor["spirit"]
        # Taunting Opener's charge lowers the ante; Measured Tempo's charges
        # sharpen every hit of this chain. Both return if it never opens.
        taunt = actor["conditions"].pop("taunting", None)
        ante = max(0, 600 - (taunt["magnitude"] if taunt else 0))
        actor["spirit"], exchange["debt"] = math.burst_ante(before, ante)
        exchange["paid_ante"] = before - actor["spirit"]
        exchange["taunting"] = taunt
        exchange["tempo"] = actor.get("tempo", 0)
        tempo = rules(build).get("measured_tempo", {}).get("amount", F(0))
        exchange["tempo_accuracy"] = str(tempo * exchange["tempo"])
        actor["tempo"] = 0
    exchange["attack_spirit"] = actor["spirit"]
    exchange["carry"] = actor["carry"]
    actor["outgoing"] = ex_id
    partners.reserve(state, exchange, partner_requests)
    partners.snapshot(state, exchange)
    state["exchanges"][ex_id] = exchange
    partners.emit(state, partners.Event("declare", actor["id"], ex_id, 1))
    if move.action in ("attack", "spell"):
        for target_id in targets:
            participant(state, target_id)["incoming"].append(f"{ex_id}:1")
    elif revival:
        # Returning is the ally's choice: the offer waits in their queue
        # unless they already chose to accept revival from allies.
        target = participant(state, targets[0])
        target["incoming"].append(f"{ex_id}:1")
        if target.get("revive") == "accept":
            accept_revival(state, target["id"], f"{ex_id}:1", support_allowed=support_allowed)
    else:
        support_exchange(state, exchange, allowed=support_allowed)
    return ex_id


def revivable(row):
    """An enrolled ally at 0 Vitality who is present to accept a revival."""
    return (
        row["status"] == "active"
        and row["hp"] <= 0
        and not row["correction"]
        and not row.get("absent")
    )


def accept_revival(state, ident, token, *, support_allowed=None):
    """The incapacitated ally accepts a pending revival Heal; it resolves now."""
    progress(state)
    row = participant(state, ident)
    exchange = get_exchange(state, token)
    if not exchange.get("revival") or token not in row["incoming"]:
        raise CombatError("No revival offer matches that token.")
    if not revivable(row):
        raise CombatError("Only a present, incapacitated participant can accept a revival.")
    row["incoming"].remove(token)
    support_exchange(state, exchange, allowed=support_allowed)


def retract(state, ident):
    """A healer withdraws an unaccepted revival offer, with a full refund."""
    actor = participant(state, ident)
    exchange = state["exchanges"].get(actor["outgoing"])
    if exchange is None or not exchange.get("revival") or exchange["phase"] != "waiting":
        raise CombatError("You have no unaccepted revival offer to withdraw.")
    cancel(state, exchange["targets"][0], f"{exchange['id']}:{exchange['hit']}")


def pass_action(state, ident):
    """Spend one action, advancing conditions without an exchange or rewards."""
    progress(state)
    row = participant(state, ident)
    if row["status"] != "active" or row["hp"] <= 0 or row.get("return_required"):
        raise CombatError("That participant is Faded, withdrawn or incapacitated.")
    if row["correction"] or row.get("absent"):
        raise CombatError("Relock your build and be present before passing.")
    if row["incoming"]:
        raise CombatError("Resolve or cancel every incoming attack before acting.")
    if row["outgoing"] or row["pose"]:
        raise CombatError(
            "Finish your outgoing exchange and acknowledge its RP with +combat/posed."
        )
    if row["turns"] >= row["turn_limit"] or row["actions_left"] <= 0:
        raise CombatError("Your personal Turn Limit is exhausted.")
    from .effects import consume_skip, initiating_executed

    opening(state)
    initiating_executed(row)
    row["recovering"] = False
    row["pressure"] = math.clamp(
        0,
        30,
        row["pressure"]
        - math.rounded(math.rule("pressure_recovery"))
        - math.rounded(
            passive(Build.from_dict(row["build"]), "exchange_end", "pressure_recovery", "pass")
        ),
    )
    row["clock"] += 1
    if value(row, "poisoned"):
        # Passing grants no resources, including damage-taken rewards.
        row["hp"] = max(0, row["hp"] - value(row, "poisoned"))
        if row["hp"] == 0:
            row["return_required"] = True
    row["conditions"] = {k: v for k, v in row["conditions"].items() if v["expires"] > row["clock"]}
    row["actions_left"] -= 1
    row["actions_spent"] += 1
    if row["actions_left"] <= 0:
        row["turns"] += 1
        row["actions_left"] = row["allowance"]
        consume_skip(row)
    row["pose"] = not row["auto"]
    partners.emit(state, partners.Event("pass", row["id"], "", 0))
    settle(state)


def consume_armed(row, used):
    """Consume only flags frozen for an executed packet, preserving later edits."""
    armed = row.setdefault("armed", {})
    for key, value in used.items():
        if armed.get(key) == value:
            armed.pop(key, None)


def action_flags(row, move, bet, *, state, targets):
    """Choose eligible flags; ineligible modifiers remain armed."""
    armed = available_armed(state, row)
    eligible = {"empower", "surge"}
    if move.action in ("attack", "spell"):
        if len(targets) == 1:
            eligible.add("burst")
        if bet:
            eligible.add("callshot")
    if (
        move.action == "assist"
        and "heal" in move.effects
        and any(revivable(participant(state, t)) for t in targets)
    ):
        eligible.add("waive")
    return {key: value for key, value in armed.items() if key in eligible}


def surge_request(used, targets, requests):
    if "surge" not in used:
        return requests
    target = used["surge"] or str(targets[0])
    if target not in [str(t) for t in targets]:
        raise CombatError("The armed Surge target must be one of this action's targets.")
    return {**(requests or {}), "party": {"kind": "surge", "target": target}}


def get_exchange(state, token):
    parts = str(token).split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        raise CombatError("Use the incoming exchange token shown by +combat.")
    exchange = state["exchanges"].get(parts[0])
    if (
        exchange is None
        or exchange["phase"] != "waiting"
        or exchange["hit"] != int(parts[1])
        or not token.startswith(f"{state['epoch']}.")
    ):
        raise CombatError("That exchange is stale, completed or superseded.")
    return exchange


def reaction(
    state, ident, token, kind, *, counter=None, empower=False, domain="", domain_effects=None
):
    progress(state)
    defender = active(state, ident)
    exchange = get_exchange(state, token)
    if token not in defender["incoming"] or defender["id"] in exchange["reactions"]:
        raise CombatError("No unaccepted incoming reaction matches that token.")
    if exchange.get("revival"):
        raise CombatError("That is a revival offer: +combat/accept or /decline it.")
    used = {
        key: value
        for key, value in available_armed(state, defender).items()
        if kind == "overpower" and key in ("counter", "empower")
    }
    empower = empower or bool(used.get("empower"))
    if "counter" in used:
        key = used["counter"]
        if key in TIERS:
            counter = Move(key=key, name=key.title(), power=TIERS[key][0], accuracy=TIERS[key][1])
        else:
            counter = next(
                (m for m in Build.from_dict(defender["build"]).moves if m.key == key), None
            )
            if counter is None:
                raise CombatError("The armed counter is not in your frozen loadout.")
    counter = counter or Move()
    if kind not in partners.reactions(exchange, defender["id"]):
        raise CombatError("Choose an available reaction; intercepted packets cannot be Evaded.")
    if kind != "overpower" and (counter != Move() or empower):
        raise CombatError("Only Overpower selects or Empowers a counter.")
    builtin_effect = (domain_effects or {}).get(counter.domain)
    chosen_domain = domain or (
        counter.domain
        if kind == "overpower"
        # Read is bought separately before reacting, never built into a counter.
        and builtin_effect != "read"
        and has_domain(Build.from_dict(defender["build"]), counter.domain)
        and kind in DOMAIN_ACTIONS.get(builtin_effect, ())
        else ""
    )
    domain_effect = (domain_effects or {}).get(chosen_domain, "")
    if domain_effect == "read":
        raise CombatError("Use +react/read before selecting your reaction.")
    if chosen_domain and defender["id"] in exchange.get("readers", ()):
        raise CombatError("Read already used this reaction's domain effect.")
    if chosen_domain and (
        not has_domain(Build.from_dict(defender["build"]), chosen_domain)
        or kind not in DOMAIN_ACTIONS.get(domain_effect, ())
    ):
        raise CombatError("That equipped domain effect does not apply to this reaction.")
    surcharge = 1 if chosen_domain and chosen_domain != counter.domain else 0
    if kind != "overpower" and defender["reserves"] < surcharge:
        raise CombatError("Insufficient Reserves for that domain effect.")
    if kind == "overpower":
        own_build = Build.from_dict(defender["build"])
        if counter.action not in ("attack", "spell"):
            raise CombatError("A counter must be Attack or Spell.")
        if counter.kind == "signature" and counter not in own_build.moves:
            raise CombatError("That counter is not in your frozen loadout.")
        try:
            reserves, _missing, blood = blood_price(
                defender, own_build, counter, move_cost(own_build, counter) + surcharge
            )
        except CombatError:
            raise CombatError("Insufficient resources for that counter.") from None
        if empower and defender["transcendence"] < 100:
            raise CombatError("Insufficient resources for that counter.")
        strain = 5 if "strain" in counter.effects else 0
        if strain and defender["hp"] <= strain:
            raise CombatError("Strain must leave at least 1 Vitality.")
        if blood and defender["hp"] - strain - blood < 1:
            raise CombatError("Blood Price must leave at least 1 Vitality.")
        defender["reserves"] -= reserves
        defender["hp"] -= strain + blood
        surcharge = 0
        if empower:
            defender["transcendence"] -= 100
    defender["reserves"] -= surcharge
    # Reserve one-use reaction benefits now. A second accepted reaction may
    # not consume the same Stance while this shared packet waits on a peer.
    frozen_conditions = {k: dict(v) for k, v in defender["conditions"].items()}
    defender["conditions"].pop(f"{kind}_stance", None)
    defender["conditions"].pop("misdirected", None)
    # Flowing Guard is spent by the next reaction attempt, whichever it is.
    defender["conditions"].pop("flowing_evade", None)
    defender["conditions"].pop("flowing_resist", None)
    if kind == "overpower":
        defender["conditions"].pop("op_penalty", None)
    exchange["reactions"][defender["id"]] = {
        "kind": kind,
        "armed": used,
        "counter": counter.as_dict(),
        "empower": empower,
        "domain_effect": domain_effect,
        "domain": chosen_domain,
        "spirit": defender["spirit"],
        "pressure": defender["pressure"],
        "conditions": frozen_conditions,
    }
    # Keep the token until the shared result commits; acceptance closes cancel.
    if len(exchange["reactions"]) + len(exchange["canceled"]) == len(exchange["targets"]):
        resolve_exchange(state, exchange)


def read_bet(state, ident, token, domain, domain_effects):
    """Insight's Read: pay 1 Reserve once to see an incoming RPS bet.

    Returns the bet ("" for none), or None when the attacker's Domain
    Resistance blocked it. The Reserve is spent either way.
    """
    progress(state)
    row = active(state, ident)
    exchange = get_exchange(state, token)
    if token not in row["incoming"] or row["id"] in exchange["reactions"]:
        raise CombatError("Read before accepting your incoming reaction.")
    if (domain_effects or {}).get(domain) != "read" or not has_domain(
        Build.from_dict(row["build"]), domain
    ):
        raise CombatError("Equip the Insight/Read domain first.")
    readers = exchange.setdefault("readers", [])
    if row["id"] not in readers:
        if row["reserves"] < 1:
            raise CombatError("Read costs 1 Reserve.")
        row["reserves"] -= 1
        readers.append(row["id"])
    if blocks(participant(state, exchange["actor"]), domain, "read"):
        return None
    return exchange["bet"]


def cancel(state, ident, token):
    """Player-owned cancellation before acceptance, including hidden results."""
    defender = participant(state, ident)
    exchange = get_exchange(state, token)
    if defender["id"] not in exchange["targets"] or token not in defender["incoming"]:
        raise CombatError("That attack is not incoming to you.")
    if defender["id"] in exchange["reactions"]:
        raise CombatError("Your reaction is already accepted. Further rollback requires staff.")
    exchange["canceled"].append(defender["id"])
    partners.emit(
        state,
        partners.Event(
            "cancel", exchange["actor"], exchange["id"], exchange["hit"], defender["id"]
        ),
    )
    defender["incoming"].remove(token)
    actor = participant(state, exchange["actor"])
    blood = exchange.get("blood") or {}
    units = min(blood.get("units", 0), exchange["cost"])
    if units:
        blood["units"] -= units
    actor["reserves"] = min(5, actor["reserves"] + exchange["cost"] - units)
    actor["hp"] = min(
        actor["max_hp"],
        actor["hp"] + exchange["strain_cost"] + units * blood.get("rate", 0),
    )
    if len(exchange["reactions"]) + len(exchange["canceled"]) == len(exchange["targets"]):
        if exchange["reactions"]:
            resolve_exchange(state, exchange)
            return
        # Nothing in this hit executed, including a pressed Burst hit.
        if exchange["empower"]:
            actor["transcendence"] = min(100, actor["transcendence"] + 100)
            exchange["empower"] = False
        if exchange["resolved"]:
            finish_exchange(state, exchange)
        else:
            actor["spirit"] = min(2000, actor["spirit"] + exchange["paid_ante"])
            if exchange.get("taunting"):
                actor["conditions"]["taunting"] = exchange["taunting"]
            actor["tempo"] = actor.get("tempo", 0) + exchange.get("tempo", 0)
            actor["outgoing"] = None
            exchange["phase"] = "canceled"


def reaction_view(state, ident, token):
    defender = participant(state, ident)
    exchange = get_exchange(state, token)
    move = Move.from_dict(exchange["move"])
    packet = partners.modifiers(exchange, ident)
    # Accuracy is declared publicly, including paid Stance costs and exposure
    # from unpaid ante. The private RPS bet and draw never enter this view.
    attack_build = Build.from_dict(participant(state, exchange["actor"])["build"])
    empowered = (
        exchange["empower"]
        and not exchange["empower_used"]
        and defender["id"]
        == next((t for t in exchange["targets"] if t not in exchange["canceled"]), None)
    )
    accuracy = (
        move.effective_accuracy
        + (2 if empowered else 0)
        - F(max(exchange["debt"], exchange["carry"]), 100)
        + F(exchange.get("tempo_accuracy", "0"))
    )
    accuracy += passive(attack_build, "declare", "accuracy", move.action) + passive(
        attack_build, "before_resolution", "accuracy", move.action
    )
    provoked = exchange["actor_conditions"].get("provoked")
    if provoked and provoked["source"] != defender["id"]:
        accuracy -= F(provoked["magnitude"], 8)
    power = (
        move.power
        + (2 if empowered else 0)
        + passive(attack_build, "declare", "power", move.action)
        + passive(attack_build, "before_resolution", "power", move.action)
    )
    own_build = Build.from_dict(defender["build"])
    penalties = tuple(
        (
            r,
            str(
                exposure(defender, own_build, r)
                + F(packet.reaction_penalty)
                + F(exchange.get("interception_penalties", {}).get(str(ident), "0"))
                + (
                    value(defender, "grappled")
                    if r == "evade"
                    else value(defender, "op_penalty")
                    + (
                        15
                        if exchange["domain_effect"] == "ambush"
                        and not blocks(defender, exchange["domain"], "ambush")
                        else 0
                    )
                    if r == "overpower"
                    else 0
                )
            ),
        )
        for r in ("evade", "resist", "overpower")
    )
    bonuses = tuple(
        (
            r,
            str(
                value(defender, f"{r}_stance")
                + value(defender, f"flowing_{r}")
                + F(packet.formation_penalty)
                + passive(own_build, "before_reaction", r, move.action)
                + passive(own_build, "before_resolution", r, move.action)
            ),
        )
        for r in ("evade", "resist", "overpower")
    )
    return ReactionView(
        move.action,
        power,
        accuracy,
        exchange["attack_spirit"],
        Build.from_dict(defender["build"]),
        defender["hp"],
        defender["reserves"],
        defender["transcendence"],
        defender["spirit"],
        defender["pressure"],
        penalties,
        bonuses,
        not bool(value(defender, "misdirected")),
        packet.damage_boost,
        packet.surge,
        partners.reactions(exchange, ident),
        # Only a bet its attacker called publicly; hidden bets stay hidden.
        public_bet=exchange["bet"] if exchange.get("public_bet") else "",
        public_shift=tuple(str(v) for v in shift(attack_build, exchange))
        if exchange.get("public_bet")
        else ("0", "0"),
    )


def resolve_exchange(state, exchange):
    from .effects import initiating_executed

    actor = participant(state, exchange["actor"])
    # Queued participants cannot relock, so their frozen builds are this
    # exchange's inputs; exchanges and reactions keep no private copies.
    attack_build = Build.from_dict(actor["build"])
    move = Move.from_dict(exchange["move"])
    token = f"{exchange['id']}:{exchange['hit']}"
    broken = False
    for target_id in exchange["targets"]:
        if target_id in exchange["canceled"]:
            continue
        initiating_executed(actor)
        defender = participant(state, target_id)
        choice = exchange["reactions"][target_id]
        consume_armed(actor, exchange.get("armed", {}))
        consume_armed(defender, choice.get("armed", {}))
        defense_build = Build.from_dict(defender["build"])
        frozen_defender = {"conditions": choice["conditions"]}
        counter = Move.from_dict(choice["counter"])
        reaction_kind = choice["kind"]
        packet = partners.modifiers(exchange, target_id)
        stance = f"{reaction_kind}_stance"
        bonus = value(frozen_defender, stance) + value(frozen_defender, f"flowing_{reaction_kind}")
        bonus += passive(defense_build, "before_reaction", reaction_kind, move.action)
        bonus += passive(defense_build, "before_resolution", reaction_kind, move.action)
        bonus += F(packet.formation_penalty)
        penalty = exposure(frozen_defender, defense_build, reaction_kind)
        penalty += F(packet.reaction_penalty) + F(
            exchange.get("interception_penalties", {}).get(target_id, "0")
        )
        if reaction_kind == "evade":
            penalty += value(frozen_defender, "grappled")
        ambushed = exchange["domain_effect"] == "ambush"
        ambush_resisted = ambushed and blocks(defender, exchange["domain"], "ambush")
        if reaction_kind == "overpower":
            penalty += value(frozen_defender, "op_penalty") + (
                15 if ambushed and not ambush_resisted else 0
            )
        # A reaction's own domain effect working against the attacker.
        slip_inside = choice.get("domain_effect") == "slip_inside"
        slip_resisted = slip_inside and blocks(actor, choice.get("domain", ""), "slip_inside")
        empowered = exchange["empower"] and not exchange["empower_used"]
        exchange["empower_used"] = exchange["empower_used"] or empowered
        power = (
            move.power
            + (2 if empowered else 0)
            + passive(attack_build, "declare", "power", move.action)
            + passive(attack_build, "before_resolution", "power", move.action)
        )
        accuracy = (
            move.effective_accuracy
            + (2 if empowered else 0)
            - F(max(exchange["carry"], exchange["debt"]), 100)
            + F(exchange.get("tempo_accuracy", "0"))
        )
        accuracy += passive(attack_build, "declare", "accuracy", move.action) + passive(
            attack_build, "before_resolution", "accuracy", move.action
        )
        provoked = exchange["actor_conditions"].get("provoked")
        if provoked and provoked["source"] != target_id:
            accuracy -= F(provoked["magnitude"], 8)
        result = math.resolve(
            attack_build,
            defense_build,
            move,
            reaction_kind,
            exchange["draw"],
            power=power,
            accuracy=accuracy,
            spirit=exchange["attack_spirit"],
            defender_spirit=choice["spirit"],
            pressure=choice["pressure"],
            penalty=penalty,
            bonus=bonus,
            rps=exchange["bet"],
            counter=counter,
            counter_power=counter.power
            + (2 if choice["empower"] else 0)
            + passive(defense_build, "declare", "power", counter.action)
            + passive(defense_build, "before_resolution", "power", counter.action),
            counter_accuracy=counter.effective_accuracy
            + (2 if choice["empower"] else 0)
            + passive(defense_build, "declare", "accuracy", counter.action)
            + passive(defense_build, "before_resolution", "accuracy", counter.action),
            slip_inside=slip_inside and not slip_resisted,
            endure=choice.get("domain_effect") == "endure",
            strain="strain" in move.effects,
            multiplier=damage_multiplier(defense_build, move.element),
            counter_multiplier=damage_multiplier(attack_build, counter.element),
            ignore_penetrating=bool(value(frozen_defender, "bulwark")),
            rps_shift=shift(attack_build, exchange),
            damage_boost=F(packet.damage_boost),
            surge=F(packet.surge),
        )
        transfer_basis = min(defender["hp"], result.burst_damage)
        actor_was_participating = participating(actor)
        target_was_participating = participating(defender)
        incoming = harm(
            defender,
            result.damage,
            half_transcendence="half_transcendence" in focused_traits(attack_build, move.element),
        )
        counter_loss = harm(
            actor,
            result.counter_damage,
            half_transcendence="half_transcendence"
            in focused_traits(defense_build, counter.element),
        )
        defender["pressure"] = min(30, defender["pressure"] + result.pressure_gain)
        defender["incoming"].remove(token)
        flowing = rules(defense_build).get("flowing_guard")
        if flowing and result.success and reaction_kind in ("evade", "resist"):
            other = "resist" if reaction_kind == "evade" else "evade"
            # Lasts until the defender's next own action ends; a Flaw's
            # negative amount works the same way as a penalty.
            defender["conditions"][f"flowing_{other}"] = {
                "magnitude": math.rounded(flowing["amount"]),
                "expires": defender["clock"] + 1,
                "source": defender["id"],
            }
        if (
            reaction_kind == "overpower"
            and not result.success
            and "bait" in rules(attack_build)
            and not exchange.get("baited")
        ):
            actor["reserves"] = min(5, actor["reserves"] + 1)
            exchange["baited"] = True
        exchange["resolved"] += 1
        exchange["stance_strengths"].append(
            math.rounded(
                math.rule("stance_defended") if result.success else math.rule("stance_full")
            )
        )
        if move.kind == "standard":
            actor["reserves"] = min(5, actor["reserves"] + 2)
        details = {
            "target": target_id,
            "hit": exchange["hit"],
            "reaction": reaction_kind,
            "draw": exchange["draw"],
            "chance": result.chance,
            "success": result.success,
            "glancing": result.glancing,
            "damage": incoming,
            "counter_damage": counter_loss,
            "pressure_gain": result.pressure_gain,
            "domain": result.domain,
        }
        if slip_resisted or (ambush_resisted and reaction_kind == "overpower"):
            details["domain_resisted"] = True
        if exchange["burst"]:
            actor["spirit"], defender["spirit"], exchange["debt"], requested, transferred = (
                math.burst_transfer(
                    transfer_basis,
                    defense_build.score("will"),
                    actor["spirit"],
                    defender["spirit"],
                    exchange["debt"],
                )
            )
            details.update(transfer_requested=requested, transfer_actual=transferred)
            broken = result.success and reaction_kind in ("evade", "overpower")
            if broken and exchange["hit"] > 1:
                condition(
                    actor,
                    "overextended",
                    value(actor, "overextended")
                    + extension(attack_build, 10 if reaction_kind == "overpower" else 5),
                    2,
                    wardable=False,
                )
                if reaction_kind == "overpower":
                    change_spirit(actor, -200)
        else:
            exchange["spirit_changes"].append(
                math.spirit_after_hit(
                    attack_build.score("will"), exchange["attack_spirit"], result.success
                )
            )
        apply_element(state, actor, defender, move.element, incoming)
        if result.success and reaction_kind == "overpower":
            apply_element(state, defender, actor, counter.element, counter_loss)
            change_spirit(
                defender,
                math.rounded(
                    100 * passive(defense_build, "after_resolution", "spirit", counter.action)
                ),
            )
        if result.domain and exchange["domain"] and not exchange["domain_used"]:
            if not apply_domain(
                state, actor, defender, exchange["domain_effect"], exchange["domain"]
            ):
                details["domain_resisted"] = True
            exchange["domain_used"] = True
        if reaction_kind == "overpower":
            for effect in counter.effects:
                if effect.endswith("_stance"):
                    condition(
                        defender,
                        effect,
                        math.rounded(
                            math.rule("stance_full")
                            if result.success
                            else math.rule("stance_defended")
                        ),
                        1,
                    )
        exchange["outcomes"].append(details)
        partners.emit(
            state,
            partners.Event(
                "packet",
                actor["id"],
                exchange["id"],
                exchange["hit"],
                target_id,
                damage=incoming,
                counter_damage=counter_loss,
                empowered=empowered,
                actor_was_participating=actor_was_participating,
                target_was_participating=target_was_participating,
            ),
        )
        change_spirit(
            actor,
            math.rounded(100 * passive(attack_build, "after_resolution", "spirit", move.action)),
        )
    for effect in move.effects:
        if effect.endswith("_stance") and exchange["stance_strengths"]:
            condition(
                actor,
                effect,
                math.rounded(
                    F(sum(exchange["stance_strengths"]), len(exchange["stance_strengths"]))
                ),
                2,
            )
    if (
        exchange["burst"]
        and not broken
        and exchange["hit"] < 3
        and actor["hp"] > 0
        and all(
            participant(state, t)["hp"] > 0
            for t in exchange["targets"]
            if t not in exchange["canceled"]
        )
    ):
        exchange["phase"] = "press"
    else:
        finish_exchange(state, exchange)
    settle(state)


def element_traits(element):
    from .conf import get

    traits = get("RP_COMBAT_ELEMENT_TRAITS").get(element, ())
    return (traits,) if isinstance(traits, str) else traits


def focused_traits(build, element):
    return (
        element_traits(element)
        if any(
            key in ("elemental-focus", "combat-focus") and tag == element
            for key, tag, level in build.abilities
        )
        else ()
    )


def apply_element(state, actor, defender, element, damage):
    if not damage:
        return
    for trait in focused_traits(Build.from_dict(actor["build"]), element):
        if trait == "drain":
            heal(actor, math.rounded(F(damage, 5) * F(3, 4) ** actor["heals"]))
        elif trait == "spirit_loss":
            change_spirit(defender, -100)
        elif trait == "normalize":
            change_spirit(
                defender,
                -min(200, defender["spirit"])
                if defender["spirit"] > 0
                else min(200, -defender["spirit"]),
            )
        elif trait == "op_penalty":
            condition(defender, "op_penalty", 10, 1)
        elif trait == "spirit_gain":
            change_spirit(actor, 100)
        elif trait == "penetrating_resist":
            condition(actor, "bulwark", 1, 2)
        elif trait == "dispel":
            for name in (
                "warded",
                "evade_stance",
                "resist_stance",
                "overpower_stance",
                "endure",
                "slip_inside",
            ):
                if name in defender["conditions"]:
                    del defender["conditions"][name]
                    break


def apply_domain(state, actor, target, effect, domain=""):
    """Host maps domain identities to these distinct, bounded behaviors.

    Returns False when the target's Domain Resistance to ``domain`` blocked
    the effect. It is checked first, so a Ward is not spent on it.
    """
    if blocks(target, domain, effect):
        return False
    if effect == "grapple":
        condition(target, "grappled", 10, 1, actor["id"])
    elif effect == "slip_inside":
        condition(actor, "slip_inside", 1, 2)
    elif effect == "endure":
        condition(actor, "endure", 1, 2)
    elif effect == "pilfer":
        amount = min(1, target["reserves"], 5 - actor["reserves"])
        target["reserves"] -= amount
        actor["reserves"] += amount
    elif effect == "treat":
        for name in ("poisoned", "grappled", "provoked"):
            if name in target["conditions"]:
                del target["conditions"][name]
                break
    elif effect == "envenom":
        condition(target, "poisoned", 3, 2, actor["id"])
    elif effect == "ward":
        condition(target, "warded", 1, 2, actor["id"])
    elif effect == "analyze":
        build = Build.from_dict(target["build"])
        traits = [
            (key, tag)
            for key, tag, level in build.abilities
            if key
            in (
                "elemental-resistance",
                "style-resistance",
                "elemental-vulnerability",
                "style-vulnerability",
            )
        ]
        actor.setdefault("information", {})[target["id"]] = {
            "name": target["name"],
            "traits": traits,
            "flaws": list(build.flaws),
        }
    elif effect == "read":
        condition(actor, "read", 1, 2, target["id"])
    elif effect == "pinpoint":
        pass  # Cover and Back-row protection require the later Party provider.
    elif effect == "exhort":
        target["transcendence"] = min(100, target["transcendence"] + 12)
    elif effect == "encore":
        # Without a Party provider this is an explicit single-target fallback.
        change_spirit(target, 200)
    elif effect == "provoke":
        condition(target, "provoked", 10, 1, actor["id"])
    elif effect == "misdirect":
        condition(target, "misdirected", 1, 1, actor["id"])
    # Ambush modifies this attack before the roll; it has no persistent copy.
    return True


def support_spirit(state, exchange, target, *, empowered=False, surge=0):
    """Ordinary support calculation shared by a primary and incidental allies."""
    actor = participant(state, exchange["actor"])
    move = Move.from_dict(exchange["move"])
    actor_build = Build.from_dict(actor["build"])
    previous = actor["support_history"].get(f"{move.action}:{target['id']}")
    active_stat = None
    if move.assist_stat:
        from .conf import get

        role = next(
            (
                k
                for k, v in get("RP_COMBAT_ROLES").items()
                if v == move.assist_stat and k in ("attack", "spell", "dispirit")
            ),
            None,
        )
        if role is None:
            raise CombatError("Assist must use a legal active stat.")
        active_stat = actor_build.score(role)
    spirit, healing, success = math.support_values(
        actor_build,
        Build.from_dict(target["build"]),
        move.action,
        exchange["draw"],
        active=active_stat,
        factor=1 + F(exchange["attack_spirit"], 4000),
        repeat=previous is not None and actor["clock"] - previous <= 3,
        heals=target["heals"],
        empower=empowered,
        surge=surge,
    )
    provoked = actor["conditions"].get("provoked")
    if provoked and provoked["source"] != target["id"]:
        spirit = math.rounded(F(9, 10) * spirit)
        healing = math.rounded(F(9, 10) * healing)
    return spirit, healing, success


def support_exchange(state, exchange, *, allowed=None):
    from .effects import initiating_executed

    actor = participant(state, exchange["actor"])
    actor_build = Build.from_dict(actor["build"])
    move = Move.from_dict(exchange["move"])
    consume_armed(actor, exchange.get("armed", {}))
    for target_id in exchange["targets"]:
        target = participant(state, target_id)
        packet = partners.modifiers(exchange, target_id)
        key = f"{move.action}:{target_id}"
        empowered = exchange["empower"] and exchange["resolved"] == 0
        spread = (
            partners.support_spread(state, exchange, target_id)
            if move.action == "assist" and not exchange["domain_used"]
            else None
        )
        recipients = []
        if spread is not None:
            for ident in spread.recipients:
                other = state["participants"].get(ident)
                if (
                    other
                    and other["side"] == actor["side"]
                    and participating(other)
                    and (allowed is None or ident in allowed)
                ):
                    recipients.append(ident)
            exchange.setdefault("support_spread", {})[target_id] = recipients
        spirit, healing, success = support_spirit(
            state, exchange, target, empowered=empowered, surge=F(packet.surge)
        )
        initiating_executed(actor)
        if spread is not None:
            spirit = math.rounded(spirit * F(spread.factor)) if target_id in recipients else 0
        actual_spirit = change_spirit(target, spirit)
        resisted = blocks(target, exchange["domain"], exchange["domain_effect"])
        if exchange["domain_effect"] == "beguile" and success and not resisted:
            change_spirit(actor, -actual_spirit)
        restored = heal(target, healing) if "heal" in move.effects else 0
        revived = exchange.get("revival") and restored > 0
        if revived:
            # A zero-effective Heal leaves them incapacitated.
            target.pop("return_required", None)
            target["recovering"] = not exchange["waive_recovery"]
        actor["support_history"][key] = actor["clock"]
        exchange["outcomes"].append(
            {
                "target": target_id,
                "hit": 1,
                "draw": exchange["draw"],
                "success": success,
                "spirit": actual_spirit,
                "healing": restored,
            }
        )
        if exchange.get("revival"):
            exchange["outcomes"][-1]["revived"] = bool(revived)
        exchange["resolved"] += 1
        if exchange["domain"] and success and not exchange["domain_used"]:
            if spread is not None and exchange["domain_effect"] == "encore":
                pass  # The spread replaces Encore's single-target fallback rider.
            elif exchange.get("waive_recovery"):
                # Medicine's alternative: no cleansing, no recovery action.
                exchange["outcomes"][-1]["recovery_waived"] = bool(revived)
            elif not apply_domain(
                state, actor, target, exchange["domain_effect"], exchange["domain"]
            ):
                exchange["outcomes"][-1]["domain_resisted"] = True
            exchange["domain_used"] = True
        partners.emit(
            state,
            partners.Event(
                "packet",
                actor["id"],
                exchange["id"],
                exchange["hit"],
                target_id,
                healing=restored,
                spirit=actual_spirit,
                potential_spirit=spirit,
                empowered=exchange["empower"] and exchange["resolved"] == 1,
                actor_was_participating=participating(actor),
                target_was_participating=participating(target),
            ),
        )
        for ident in recipients:
            if ident == target_id or ident in exchange["targets"]:
                continue
            other = participant(state, ident)
            amount, _healing, _success = support_spirit(state, exchange, other, empowered=empowered)
            actual = change_spirit(other, math.rounded(amount * F(spread.factor)))
            actor["support_history"][f"assist:{ident}"] = actor["clock"]
            exchange["outcomes"].append(
                {
                    "target": ident,
                    "hit": 1,
                    "draw": exchange["draw"],
                    "success": True,
                    "spirit": actual,
                    "healing": 0,
                    "incidental": True,
                }
            )
    taunting = rules(actor_build).get("taunting_opener")
    if taunting and move.action == "dispirit" and any(o["success"] for o in exchange["outcomes"]):
        # One charge for the next Burst, gone after the next own action.
        condition(actor, "taunting", math.rounded(taunting["amount"]), 2, wardable=False)
    condition(actor, "vulnerable", 20, 2, wardable=False)
    finish_exchange(state, exchange)


@partners.atomic_requests
def press(state, ident, draw, *, stop=False, empower=False, partner_requests=None):
    progress(state)
    actor = participant(state, ident)
    exchange = state["exchanges"].get(actor["outgoing"])
    if exchange is None or exchange["phase"] != "press":
        raise CombatError("No open Burst is waiting for press or stop.")
    if stop:
        # Closing executed hits is cleanup: an actor incapacitated mid-Burst
        # must still be able to release the exchange (and the fight's end).
        finish_exchange(state, exchange)
        return
    active(state, ident)
    used = {
        key: value
        for key, value in available_armed(state, actor).items()
        if key in ("empower", "surge")
    }
    empower = empower or bool(used.get("empower"))
    partner_requests = surge_request(used, exchange["targets"], partner_requests)
    if actor["incoming"]:
        raise CombatError("Clear incoming reactions before pressing the Burst.")
    move = Move.from_dict(exchange["move"])
    for target in exchange["targets"]:
        active(state, target)
    build = Build.from_dict(actor["build"])
    try:
        reserves, missing, blood = blood_price(actor, build, move, exchange["cost"])
    except CombatError:
        reserves = None
    if reserves is None or actor["hp"] - exchange["strain_cost"] - blood < 1:
        if partner_requests:
            raise CombatError("The Burst cannot be afforded; no partner resource was spent.")
        # The chain cannot be afforded; it ends as a stop.
        finish_exchange(state, exchange)
        return
    if empower and actor["transcendence"] < 100:
        raise CombatError("Empower requires 100 Transcendence.")
    actor["reserves"] -= reserves
    actor["hp"] -= exchange["strain_cost"] + blood
    exchange["blood"] = {"units": missing, "rate": blood // missing if missing else 0}
    if empower:
        actor["transcendence"] -= 100
    exchange["empower"] = empower
    exchange["armed"] = used
    exchange["hit"] += 1
    exchange.update(
        phase="waiting",
        reactions={},
        canceled=[],
        draw=draw,
        strain_paid=False,
        empower_used=False,
        stance_strengths=[],
    )
    exchange["attack_spirit"] = actor["spirit"]
    exchange["covered_targets"] = []
    exchange["interception_penalties"] = {}
    partners.reserve(state, exchange, partner_requests)
    partners.snapshot(state, exchange)
    partners.emit(state, partners.Event("declare", actor["id"], exchange["id"], exchange["hit"]))
    condition(
        actor, "overextended", value(actor, "overextended") + extension(build, 5), 2, wardable=False
    )
    for target in exchange["targets"]:
        participant(state, target)["incoming"].append(f"{exchange['id']}:{exchange['hit']}")


def finish_exchange(state, exchange):
    actor = participant(state, exchange["actor"])
    if exchange["phase"] in ("done", "canceled"):
        return
    if not exchange["resolved"]:
        raise CombatError("No executed exchange to finish.")
    if exchange["spirit_changes"]:
        change_spirit(
            actor, math.rounded(F(sum(exchange["spirit_changes"]), len(exchange["spirit_changes"])))
        )
    actor["carry"] = max(actor["carry"], exchange["debt"]) if exchange["debt"] else 0
    build = Build.from_dict(actor["build"])
    action = exchange["move"]["action"]
    actor["pressure"] = math.clamp(
        0,
        30,
        actor["pressure"]
        - math.rounded(math.rule("pressure_recovery"))
        - math.rounded(passive(build, "exchange_end", "pressure_recovery", action)),
    )
    actor["reserves"] = math.clamp(
        0, 5, actor["reserves"] + math.rounded(passive(build, "exchange_end", "reserves", action))
    )
    actor["transcendence"] = math.clamp(
        0,
        100,
        actor["transcendence"]
        + 8
        - math.rounded(rules(build).get("tactician", {}).get("transcendence", 0))
        + math.rounded(passive(build, "exchange_end", "transcendence", action)),
    )
    tempo = rules(build).get("measured_tempo")
    if tempo and not exchange["burst"]:
        # A real completed exchange, never recovery or a canceled attack.
        actor["tempo"] = min(math.rounded(tempo["cap"]), actor.get("tempo", 0) + 1)
    actor["clock"] += 1
    if value(actor, "poisoned"):
        eligible = participating(actor)
        source = actor["conditions"]["poisoned"].get("source", "")
        loss = harm(actor, value(actor, "poisoned"))
        if source in state["participants"] and source != actor["id"]:
            partners.emit(
                state,
                partners.Event(
                    "hostile_damage",
                    source,
                    exchange["id"],
                    0,
                    actor["id"],
                    damage=loss,
                    target_was_participating=eligible,
                ),
            )
    actor["conditions"] = {
        k: v for k, v in actor["conditions"].items() if v["expires"] > actor["clock"]
    }
    spent = 1 if exchange["burst"] else len(exchange["targets"]) - len(exchange["canceled"])
    actor["actions_left"] -= spent
    actor["actions_spent"] += spent
    if actor["actions_left"] <= 0:
        actor["turns"] += 1
        actor["actions_left"] = actor["allowance"]
        from .effects import consume_skip

        consume_skip(actor)
    actor["outgoing"] = None
    actor["pose"] = not actor["auto"]
    exchange["phase"] = "done"
    partners.emit(
        state, partners.Event("exchange_end", actor["id"], exchange["id"], exchange["hit"])
    )
    # Poison at the end of an own action can incapacitate the actor.
    settle(state)


def redirect(
    state,
    token,
    original_id,
    replacement_id,
    kind,
    *,
    counter=None,
    empower=False,
    domain="",
    domain_effects=None,
    reaction_penalty="0",
):
    """Atomically intercept and react; the caller checks party/ignore consent.

    Original packet modifiers/draw/costs stay fixed. A Burst remains the
    same exchange against the replacement; later hits declare fresh inputs.
    Even direct pure-engine callers get no partial transfer on failure.
    """
    candidate = interception_state(state, token, original_id, replacement_id, reaction_penalty)
    reaction(
        candidate,
        replacement_id,
        token,
        kind,
        counter=counter,
        empower=empower,
        domain=domain,
        domain_effects=domain_effects,
    )
    state.clear()
    state.update(candidate)


def interception_view(state, token, original_id, replacement_id, *, reaction_penalty="0"):
    """Public Cover estimates without accepting, revealing or spending anything."""
    candidate = interception_state(state, token, original_id, replacement_id, reaction_penalty)
    return reaction_view(candidate, replacement_id, token)


def interception_state(state, token, original_id, replacement_id, reaction_penalty):
    """Detached handoff candidate shared by preview and atomic acceptance."""
    candidate = deepcopy(state)
    progress(candidate)
    original = participant(candidate, original_id)
    replacement = active(candidate, replacement_id)
    exchange = get_exchange(candidate, token)
    penalty = partners.number(reaction_penalty)
    if not 0 <= penalty <= 100:
        raise CombatError("Interception reaction penalty must be between 0 and 100.")
    if (
        original["id"] not in exchange["targets"]
        or token not in original["incoming"]
        or exchange["reactions"]
        or exchange.get("revival")
        or exchange.get("covered_targets")
        or (exchange["burst"] and exchange.get("redirects"))
        or replacement["id"] in exchange["targets"]
        or replacement["side"] != original["side"]
        or replacement["incoming"]
        or replacement["outgoing"]
    ):
        raise CombatError("That packet cannot be intercepted by this participant.")
    index = exchange["targets"].index(original["id"])
    exchange["targets"][index] = replacement["id"]
    original["incoming"].remove(token)
    replacement["incoming"].append(token)
    snapshots = exchange.get("partner_modifiers", {})
    if original["id"] in snapshots:
        snapshots[replacement["id"]] = snapshots.pop(original["id"])
    exchange["covered_targets"] = [replacement["id"]]
    exchange["interception_penalties"] = {replacement["id"]: str(penalty)}
    exchange.setdefault("redirects", []).append(
        {"from": original["id"], "to": replacement["id"], "hit": exchange["hit"]}
    )
    return candidate


def fade(state, ident, *, withdraw=False):
    row = participant(state, ident)
    if row["incoming"] or row["outgoing"]:
        raise CombatError("Cancel or finish pending exchanges before leaving the fight.")
    if row["status"] == "withdrawn":
        raise CombatError("You have already withdrawn.")
    if withdraw:
        row["status"], row["hp"] = "withdrawn", 0
        row["return_required"] = True
        row.pop("faded_hp", None)
    else:
        row["faded_hp"] = row["hp"]
        row["status"] = "faded"
    if not state["paused"] and not any(
        p["status"] == "active" and p["hp"] > 0 for p in state["participants"].values()
    ):
        state["paused"], state["pause_reason"] = True, "faded"


def correction(state, ident, *, build=None):
    row = participant(state, ident)
    if row["incoming"] or row["outgoing"]:
        raise CombatError("Clear pending exchanges before correcting your loadout.")
    if build is None:
        row["correction"] = True
    else:
        row["build"] = build.as_dict()
        row["correction"] = False


def reduce_cap(state, ident, limit):
    row = participant(state, ident)
    if type(limit) is not int or not max(1, row["turns"]) <= limit <= row["turn_limit"]:
        raise CombatError("Choose a reduced cap no lower than turns already used.")
    row["turn_limit"] = limit


def available_armed(state, row):
    """Keep a committed modifier reserved for its first pending packet only."""
    reserved = set()
    for exchange in state["exchanges"].values():
        if exchange["phase"] != "waiting":
            continue
        if exchange["actor"] == row["id"]:
            reserved.update(exchange.get("armed", {}))
        reserved.update(exchange.get("reactions", {}).get(row["id"], {}).get("armed", {}))
    return {k: v for k, v in row.get("armed", {}).items() if k not in reserved}
