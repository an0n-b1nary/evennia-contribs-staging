# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pure Party provider; combat owns resolution and commits."""

from copy import deepcopy
from fractions import Fraction as F

from evennia_rp_combat import engine, partners

from . import boss, conf, rules, subjects, synergy


def snapshot(state, declaration):
    actor, target = declaration.actor_id, declaration.target_id
    own, other = rules.position(state, actor), rules.position(state, target)
    back = rules.protected(state, target)
    pinpoint = declaration.domain_effect == "pinpoint" and not engine.blocks(
        state["participants"][target], declaration.domain, "pinpoint"
    )
    penalty = F(0)
    if own != "flex" and other != "flex":
        penalty = F(20 if own == "back" else 0) + (20 if back and not pinpoint else 0)
    if "long_range" in declaration.effects:
        penalty /= 2
    key = rules.party_id(state, actor)
    counted = rules.counted(state, key) if key else []
    return partners.PacketModifiers(
        formation_penalty=penalty,
        damage_boost=rules.boost(state, key) if declaration.action in ("attack", "spell") else 0,
        surge=synergy.potency(state, declaration),
        cover_eligible=bool(
            rules.party_id(state, target)
            and rules.position(state, target) == "back"
            and rules.member(state, target).get("cover")
        ),
        auto_resolve=not (other == "back" and rules.member(state, target).get("cover")),
        facts=(
            ("actor_position", own),
            ("target_position", other),
            ("front_protection", str(back)),
            ("counted", ",".join(counted)[:200]),
            ("average_spirit", str(rules.average(state, key)) if key else "0"),
        ),
    )


def support(state, declaration):
    if declaration.domain_effect != "encore":
        return None
    key = rules.party_id(state, declaration.target_id)
    if not key:
        return None
    recipients = tuple(rules.counted(state, key))
    return partners.SupportSpread(recipients, conf.get("RP_PARTY_ENCORE_FACTOR"))


def transition(state, event):
    section = state["partners"]["party"]
    data = section["data"]
    if event.kind == "packet" and event.exchange_id:
        exchange = state["exchanges"][event.exchange_id]
        action = exchange["move"]["action"]
        key = rules.party_id(state, event.target_id)
        if key and (
            event.healing > 0
            or (action == "assist" and event.potential_spirit > 0)
            or (action == "dispirit" and event.potential_spirit < 0)
        ):
            data["pending_support"][event.exchange_id] = {
                "source": event.actor_id,
                "party": key,
                "kind": "rally" if action == "assist" else "rattle",
                "points": str(partners.number(conf.get("RP_PARTY_SUPPORT_POINTS"))),
                "exchange": event.exchange_id,
            }
    elif event.kind in ("exchange_end", "recovery"):
        affected = rules.party_id(state, event.actor_id)
        data["support"] = {
            source: entry
            for source, entry in data["support"].items()
            if source != event.actor_id
            and not (
                entry["party"] == affected
                and source in state["participants"]
                and rules.finished(state["participants"][source])
            )
        }
        entry = data["pending_support"].pop(event.exchange_id, None)
        if entry is not None:
            entry["source_clock"] = state["participants"][event.actor_id]["clock"]
            entry["party_clocks"] = {
                ident: state["participants"][ident]["clock"]
                for ident in rules.roster(state, entry["party"])
            }
            data["support"][event.actor_id] = entry
    notices = synergy.transition(state, event)
    notices.extend(boss.transition(state, event))
    return partners.Transition(section, tuple(notices))


def status(state, subject_id):
    state = deepcopy(state)
    synergy.reconcile(state)
    lines = []
    for key, row in rules.data(state)["parties"].items():
        if row["dissolved"]:
            continue
        names = []
        for ident in rules.roster(state, key):
            participant = state["participants"][ident]
            names.append(
                f"{participant['name']} ({rules.position(state, ident)}{' Cover on' if rules.member(state, ident).get('cover') else ''}{'' if engine.participating(participant) else ', unavailable'})"
            )
        lines.append(
            f"Party {key}: {row['name']} / side {row['side']}; boost {rules.boost(state, key)}%; Spirit {rules.average(state, key)}."
        )
        frozen = (
            f" ({synergy.pool(state, key)} retained, pool frozen)"
            if not rules.counted(state, key)
            else ""
        )
        lines.append(
            f"  Synergy {synergy.available(state, key)} available, {synergy.held(state, key)} reserved; cap {synergy.cap(state, key)}{frozen}."
        )
        lines.extend(f"  {value}" for value in names)
        proposal = rules.data(state)["proposals"].get(key)
        if proposal:
            missing = set(rules.counted(state, key)) - set(proposal["yes"])
            lines.append(
                f"  Dissolution awaits: {', '.join(state['participants'][ident]['name'] for ident in sorted(missing)) or 'clear queues'}."
            )
    invitation = rules.data(state)["invitations"].get(str(subject_id))
    if invitation:
        lines.append(f"Party invitation: {invitation['party']}; +party/accept or /decline.")
    if rules.party_id(state, subject_id):
        turn = state["participants"][subject_id]["turns"]
        used = [
            row["status"]
            for row in rules.data(state)["surges"].values()
            if row["actor"] == subject_id and row["turn"] == turn and row["status"] != "refunded"
        ]
        lines.append(
            f"Your Team Surge this personal turn: {used[0] if used else 'available (requires Synergy and a legal action)'}."
        )
    lines.extend(boss.lines(state, subject_id))
    return tuple(lines) or ("No tactical parties. Unpartied combat remains available.",)


PROVIDER = partners.Provider(
    snapshot=snapshot,
    upgrade=rules.upgrade,
    transition=transition,
    status=status,
    help=lambda state, subject: (
        "+party: optional tactical teams within a side. See help +party and the Party guide.",
    ),
    support=support,
    reserve=synergy.reserve,
    subject_snapshot=subjects.snapshot,
)
