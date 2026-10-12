# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact shared resources and one-packet reservations, over saved state only."""

from fractions import Fraction as F

from evennia_rp_combat import engine, partners
from evennia_rp_combat.data import CombatError

from . import conf, rules


def cap(state, key):
    return 100 * min(len(rules.counted(state, key)), 5)


def held(state, key):
    return sum(
        (
            partners.number(row["cost"])
            for row in rules.data(state)["surges"].values()
            if row["party"] == key and row["status"] == "reserved"
        ),
        F(0),
    )


def pool(state, key):
    return partners.number(rules.party(state, key)["synergy"])


def available(state, key):
    value = pool(state, key)
    maximum = cap(state, key)
    return min(value, max(0, maximum - held(state, key))) if maximum else F(0)


def target(exchange, row):
    """A reservation follows the frozen packet through its single Cover."""
    ident = row["target"]
    for redirect in exchange.get("redirects", ()):
        if redirect["hit"] == row["hit"] and redirect["from"] == ident:
            ident = redirect["to"]
    return ident


def reconcile(state):
    """Settle packets executed/canceled while absent; clamp only live pools.

    No historical earning is replayed after reinstalling. The core outcomes
    and cancellation state settle retained reservations exactly once.
    """
    data = rules.data(state)
    notices = []
    for row in data["surges"].values():
        if row["status"] != "reserved":
            continue
        exchange = state["exchanges"].get(row["exchange"])
        if exchange is None:
            continue  # A new declaration reserves before it is installed.
        ident = target(exchange, row)
        if any(
            o["hit"] == row["hit"] and o["target"] == ident and not o.get("incidental")
            for o in exchange["outcomes"]
        ):
            row["status"] = "executed"
        elif exchange["hit"] == row["hit"] and ident in exchange["canceled"]:
            row["status"] = "refunded"
            party = data["parties"][row["party"]]
            if not party["dissolved"]:
                party["synergy"] = str(
                    partners.number(party["synergy"]) + partners.number(row["cost"])
                )
                notices.append(
                    f"Team Surge: {state['participants'][row['actor']]['name'][:60]}'s unexecuted packet refunded {row['cost']} Synergy to {party['name']}; its use is released."
                )
    for key, row in data["parties"].items():
        maximum = cap(state, key)
        if row["dissolved"]:
            row["synergy"] = "0"
        elif maximum:
            old = partners.number(row["synergy"])
            new = min(old, max(0, maximum - held(state, key)))
            if new < old:
                row["synergy"] = str(new)
                notices.append(
                    f"{row['name']}: Synergy clamped by {old - new} to {new} available (cap {maximum}, {held(state, key)} reserved)."
                )
        # No counted members: freeze the retained balance and reservations.
    return notices


def reserve(state, declaration, request):
    if set(request) != {"kind", "target"} or request["kind"] != "surge":
        raise CombatError("Use a Team Surge request naming one declared target.")
    actor = engine.active(state, declaration.actor_id)
    if actor["turns"] >= actor["turn_limit"] or declaration.action not in (
        "attack",
        "spell",
        "assist",
        "dispirit",
    ):
        raise CombatError("Team Surge requires an ordinary legal outgoing action.")
    key = rules.party_id(state, actor["id"])
    if not key:
        raise CombatError("Join a party before spending Synergy.")
    notices = reconcile(state)
    data = rules.data(state)
    if any(
        row["actor"] == actor["id"]
        and row["turn"] == actor["turns"]
        and row["status"] != "refunded"
        for row in data["surges"].values()
    ):
        raise CombatError("Team Surge is already reserved or used this personal turn.")
    cost = partners.number(conf.get("RP_PARTY_SURGE_COST"))
    if available(state, key) < cost:
        raise CombatError(f"Team Surge needs {cost} available Synergy.")
    ident = f"{declaration.exchange_id}:{declaration.hit}"
    if ident in data["surges"]:
        raise CombatError("That packet already has a Team Surge reservation.")
    data["parties"][key]["synergy"] = str(pool(state, key) - cost)
    potency = str(partners.number(conf.get("RP_PARTY_SURGE_POINTS")))
    data["surges"][ident] = {
        "actor": actor["id"],
        "party": key,
        "target": declaration.target_id,
        "exchange": declaration.exchange_id,
        "hit": declaration.hit,
        "turn": actor["turns"],
        "cost": str(cost),
        "potency": potency,
        "status": "reserved",
    }
    notices.append(
        f"Team Surge: {actor['name'][:60]} reserved {cost} Synergy from {rules.party(state, key)['name']} for +{potency}% primary output against {state['participants'][declaration.target_id]['name'][:60]} in {ident}."
    )
    return partners.Transition(state["partners"]["party"], tuple(notices))


def potency(state, declaration):
    row = rules.data(state)["surges"].get(f"{declaration.exchange_id}:{declaration.hit}")
    return (
        row["potency"]
        if row and row["status"] == "reserved" and row["target"] == declaration.target_id
        else "0"
    )


def award(state, key, amount, *, before=()):
    if not key or amount <= 0:
        return
    row = rules.party(state, key)
    counted = set(rules.counted(state, key)) | {
        ident for ident in before if rules.party_id(state, ident) == key
    }
    maximum = 100 * min(len(counted), 5)
    row["synergy"] = str(min(pool(state, key) + amount, max(0, maximum - held(state, key))))


def transition(state, event):
    notices = reconcile(state)
    data = rules.data(state)
    awards = data["synergy_awards"]
    if event.kind == "packet":
        marker = f"packet/{event.exchange_id}/{event.hit}/{event.target_id}"
        if marker not in awards:
            awards[marker] = True
            actor, victim = (
                state["participants"][event.actor_id],
                state["participants"][event.target_id],
            )
            coefficient = partners.number(conf.get("RP_PARTY_DAMAGE_SYNERGY"))
            if actor["side"] != victim["side"]:
                if event.target_was_participating:
                    award(
                        state,
                        rules.party_id(state, victim["id"]),
                        coefficient * event.damage,
                        before=(victim["id"],),
                    )
                if event.actor_was_participating:
                    award(
                        state,
                        rules.party_id(state, actor["id"]),
                        coefficient * event.counter_damage,
                        before=(actor["id"],),
                    )
            empowered = f"empower/{event.exchange_id}"
            if event.empowered and empowered not in awards:
                awards[empowered] = True
                award(
                    state,
                    rules.party_id(state, actor["id"]),
                    partners.number(conf.get("RP_PARTY_EMPOWER_SYNERGY")),
                    before=(actor["id"],),
                )
    elif event.kind == "hostile_damage":
        marker = f"hostile/{event.exchange_id}/{event.hit}/{event.target_id}"
        if marker not in awards:
            awards[marker] = True
            actor, victim = (
                state["participants"][event.actor_id],
                state["participants"][event.target_id],
            )
            if event.target_was_participating and actor["side"] != victim["side"]:
                award(
                    state,
                    rules.party_id(state, victim["id"]),
                    partners.number(conf.get("RP_PARTY_DAMAGE_SYNERGY")) * event.damage,
                    before=(victim["id"],),
                )
    elif event.kind == "exchange_end":
        marker = f"exchange/{event.exchange_id}"
        if marker not in awards:
            awards[marker] = True
            award(
                state,
                rules.party_id(state, event.actor_id),
                partners.number(conf.get("RP_PARTY_EXCHANGE_SYNERGY")),
                before=(event.actor_id,),
            )
    notices.extend(reconcile(state))
    return notices
