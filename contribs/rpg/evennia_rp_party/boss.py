# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Manual encounter challenges over saved state; no models or random draws.

The coordinator supplies bound Contest results, preview tokens and Tank
draws. Combat owns damage, resource awards, skipped turns and checkpoints.
"""

import hashlib
import json
from copy import deepcopy
from fractions import Fraction as F
from functools import wraps

from evennia_rp_combat import effects, engine
from evennia_rp_combat.data import CombatError
from evennia_rp_combat.partners import number

from . import conf, rules

KINDS = ("tank", "dps", "support", "pressure", "special", "contest")
DEFAULTS = {
    "easy": {
        "tank": "24",
        "dps": "12",
        "support": "5",
        "pressure": "-1",
        "failure": "8",
        "backlash": "1/2",
        "fraction": "1/4",
    },
    "balanced": {
        "tank": "35",
        "dps": "18",
        "support": "8",
        "pressure": "-3",
        "failure": "12",
        "backlash": "1/2",
        "fraction": "1/2",
    },
    "hard": {
        "tank": "45",
        "dps": "24",
        "support": "12",
        "pressure": "-6",
        "failure": "16",
        "backlash": "1/2",
        "fraction": "3/4",
    },
}


def atomic(func):
    @wraps(func)
    def apply(state, *args, **kwargs):
        candidate = deepcopy(state)
        value = func(candidate, *args, **kwargs)
        state.clear()
        state.update(candidate)
        return value

    return apply


def presets():
    from evennia_rp_rules._config import setting

    values = setting("RP_PARTY_CHECK_PRESETS", DEFAULTS)
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise CombatError("Boss Check presets need easy, balanced and hard.")
    for profile in values.values():
        if not isinstance(profile, dict) or set(profile) != set(DEFAULTS["balanced"]):
            raise CombatError("Each Boss Check preset needs the documented numeric fields.")
        for key, value in profile.items():
            value = number(value)
            if not (
                -10 <= value <= 20
                if key == "pressure"
                else 0 < value <= 1
                if key in ("fraction", "backlash")
                else 0 < value <= 1000
            ):
                raise CombatError("Boss Check preset numbers are outside their documented bounds.")
    return values


def get(state, ident):
    row = rules.data(state)["checks"].get(str(ident))
    if row is None:
        raise CombatError("Choose a Boss Check identity from +bosscheck.")
    return row


def pending(state, party):
    return next(
        (
            row
            for row in rules.data(state)["checks"].values()
            if row["party"] == party and row["status"] == "pending"
        ),
        None,
    )


def membership(state, ident, *, joining=None, dissolving=None):
    """Check locks add no restrictions on Formation, defense or Fade."""
    if joining and pending(state, joining):
        raise CombatError("That Party's Boss Check roster is locked until it ends.")
    key = dissolving or rules.party_id(state, ident)
    check = pending(state, key) if key else None
    if check and (dissolving or str(ident) not in check["withdrawn"]):
        raise CombatError("Cancel the Party's Check or withdraw your participation before leaving.")


def eligible(state, check):
    return [
        ident
        for ident in check["cohort"]
        if ident not in check["withdrawn"] and engine.participating(state["participants"][ident])
    ]


def budget(row):
    return max(0, (row["turn_limit"] - row["turns"] - 1) * row["allowance"] + row["actions_left"])


@atomic
def issue(
    state,
    boss,
    parties,
    kind,
    *,
    difficulty="balanced",
    options=None,
    contest=None,
    contest_difficulty=None,
):
    engine.progress(state)
    boss = str(boss)
    actor = rules.clear_queue(state, boss)
    engine.active(state, boss)
    if actor["allowance"] < 2 or not budget(actor):
        raise CombatError("An active Boss Mode character with remaining turns issues Checks.")
    if kind not in KINDS or difficulty not in DEFAULTS:
        raise CombatError(
            "Choose Tank, DPS, Support, Pressure, Special or Contest; easy/balanced/hard."
        )
    if not parties or len(set(parties)) != len(parties):
        raise CombatError("Name distinct opposing Parties.")
    options = dict(options or {})
    allowed = {"requirement", "hint"} if kind == "special" else {"value"}
    if set(options) - allowed:
        raise CombatError("Unknown Boss Check option for this type.")
    if kind == "special" and any(not options.get(key) for key in ("requirement", "hint")):
        raise CombatError(
            "Special Checks need a public requirement and helpful hint; interpret generously."
        )
    if any(
        not isinstance(value, str) or len(value) > 320 or any(ord(char) < 32 for char in value)
        for value in options.values()
    ):
        raise CombatError("Boss Check options must be bounded printable text.")
    if "value" in options:
        value = number(options["value"])
        bounds = (-10, 20) if kind == "pressure" else (0, 1) if kind == "contest" else (0, 1000)
        if not bounds[0] <= value <= bounds[1] or (
            kind in ("tank", "dps", "contest") and value <= 0
        ):
            raise CombatError("That challenge value is outside its supported bounds.")
    profile = {key: str(number(value)) for key, value in presets()[difficulty].items()}
    result = []
    data = rules.data(state)
    engine.opening(state)
    for key in parties:
        party = rules.party(state, key)
        cohort = list(rules.counted(state, key))
        if party["side"] == actor["side"] or not cohort:
            raise CombatError("Challenge an opposing Party with at least one eligible member.")
        if pending(state, key):
            raise CombatError("That Party already has an unresolved Boss Check.")
        roster = rules.roster(state, key)
        markers = [f"{boss}/{actor['turns']}/{ident}" for ident in roster]
        if any(marker in data["check_issued"] for marker in markers):
            raise CombatError("This boss already challenged that cohort this personal turn.")
        if kind == "contest" and (contest is None or set(cohort) - contest.keys()):
            raise CombatError(
                "Contest support and frozen approaches are required for every target."
            )
        ident = f"{state['epoch']}.c{data['next_check']}"
        data["next_check"] += 1
        data["checks"][ident] = {
            "id": ident,
            "boss": boss,
            "party": key,
            "kind": kind,
            "difficulty": difficulty,
            "profile": profile,
            "options": options,
            "status": "pending",
            "roster": roster,
            "cohort": cohort,
            "withdrawn": [],
            "initial": {
                member: {
                    field: state["participants"][member][field]
                    for field in ("clock", "turns", "actions_left", "allowance", "actions_spent")
                }
                for member in cohort
            },
            "damage": {},
            "attempts": {},
            "allowed": (contest or {}),
            "contest_difficulty": contest_difficulty,
            "contest_sources": {
                member: deepcopy(
                    state["participants"][member].get("partner_subjects", {}).get("party")
                )
                for member in cohort
            }
            if kind == "contest"
            else {},
            "result": None,
            "canceled_by": "",
            "reason": "",
        }
        data["check_issued"].update(dict.fromkeys(markers, True))
        data["proposals"].pop(key, None)
        result.append(ident)
    return result


def cancel(state, ident, actor, *, individual=False, reason=""):
    check = get(state, ident)
    actor = str(actor)
    if check["status"] != "pending":
        raise CombatError("That Check has ended; committed consequences require staff recovery.")
    if actor not in check["roster"] and (individual or actor != check["boss"]):
        raise CombatError("Only a challenged member or the boss can cancel this Check.")
    if individual:
        if actor not in check["roster"] or actor in check["withdrawn"]:
            raise CombatError("You have no pending participation in that Check.")
        check["withdrawn"].append(actor)
        if set(check["cohort"]) <= set(check["withdrawn"]):
            check["status"] = "canceled"
    else:
        check["status"] = "canceled"
    check["canceled_by"], check["reason"] = actor, reason


def reconcile(state):
    notices = []
    for check in rules.data(state)["checks"].values():
        if check["status"] != "pending":
            continue
        actor = state["participants"].get(check["boss"])
        if state["ended"] or not actor or actor["hp"] <= 0 or actor["status"] == "withdrawn":
            check["status"], check["reason"] = "canceled", "Boss unavailable or fight ended"
            notices.append(
                f"Boss Check {check['id']} canceled without consequences: {check['reason']}."
            )
    return notices


def transition(state, event):
    if event.kind == "packet":
        for check in rules.data(state)["checks"].values():
            if check["status"] != "pending" or check["kind"] != "dps":
                continue
            for source, target, loss in (
                (event.actor_id, event.target_id, event.damage),
                (event.target_id, event.actor_id, event.counter_damage),
            ):
                if (
                    target == check["boss"]
                    and source in check["cohort"]
                    and source not in check["withdrawn"]
                    and loss > 0
                ):
                    marker = f"{event.exchange_id}/{event.hit}/{source}/{target}"
                    check["damage"].setdefault(marker, loss)
    return reconcile(state)


def required(check, n):
    kind = check["kind"]
    if "value" in check["options"]:
        value = number(check["options"]["value"])
    else:
        value = number(check["profile"].get(kind, "0"))
    if kind in ("tank", "dps"):
        return (n * value).__ceil__()
    if kind == "contest":
        return max(
            1, (n * number(check["options"].get("value", check["profile"]["fraction"]))).__ceil__()
        )
    if kind == "support":
        return value
    if kind == "pressure":
        return value * 100
    return None


def warnings(state, check):
    ids = eligible(state, check)
    notes = []
    if check["kind"] == "special":
        notes.append(
            "Explain the controller's Special pass/fail judgment with a public acknowledgment."
        )
    if len(ids) != len(check["cohort"]):
        notes.append(f"Effective size changed: {len(check['cohort'])} -> {len(ids)}.")
    progressed = [
        F(
            state["participants"][ident]["actions_spent"]
            - check["initial"][ident]["actions_spent"],
            check["initial"][ident]["allowance"],
        )
        for ident in ids
    ]
    if len(set(progressed)) > 1:
        notes.append("Uneven response progress; some members may still need to respond.")
    if any(value.denominator != 1 for value in progressed):
        notes.append("Some members are still partway through a response turn.")
    if check["kind"] in ("dps", "support", "pressure") and not any(progressed):
        notes.append(
            "No response actions have completed since issuance; opponents may not be ready."
        )
    if check["kind"] == "contest" and any(ident not in check["attempts"] for ident in ids):
        notes.append("Missing Contest responses will count as failures if resolved now.")
    if check["kind"] in ("dps", "support", "pressure") and any(
        not budget(state["participants"][i]) for i in ids
    ):
        notes.append("Some members have exhausted their initiating action budget.")
    if check["kind"] == "tank" and not any(rules.position(state, i) == "front" for i in ids):
        notes.append("No eligible Front: the frontline collapses if resolved now.")
    if check["kind"] == "support" and required(check, len(ids)) > number(
        conf.get("RP_PARTY_BOOST_CAP")
    ):
        notes.append("The Support requirement exceeds the configured boost cap.")
    if check["kind"] == "support" and rules.boost(state, check["party"]) >= required(
        check, len(ids)
    ):
        notes.append("The Support requirement is already satisfied; maintain it until resolution.")
    if check["kind"] == "pressure" and state["participants"][check["boss"]]["spirit"] <= required(
        check, len(ids)
    ):
        notes.append("The Pressure requirement is already satisfied; maintain it until resolution.")
    return notes


def boundary(state, check):
    engine.progress(state)
    if check["status"] != "pending":
        raise CombatError("That Check has ended; committed consequences require staff recovery.")
    engine.active(state, check["boss"])
    ids = eligible(state, check)
    if not ids:
        raise CombatError("No eligible Check targets remain; suspend or cancel without rewards.")
    for ident in set(check["roster"]) | {check["boss"]}:
        row = state["participants"][ident]
        if row["incoming"] or row["outgoing"]:
            raise CombatError("Finish relevant pending exchanges before resolving this Check.")
    return ids


def fingerprint(state, ident, verdict):
    candidate = deepcopy(state)
    candidate.pop("notices", None)
    for row in candidate["participants"].values():
        row.pop("last_activity", None)
    payload = [candidate, str(ident), verdict]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def preview(state, ident, *, verdict=None, contest_available=True):
    check = get(state, ident)
    ids = boundary(state, check)
    if check["kind"] == "contest" and not contest_available:
        raise CombatError("Contest provider unavailable; retain, resume or cancel this Check.")
    if check["kind"] == "special" and type(verdict) is not bool:
        raise CombatError("The boss controller must explicitly choose pass or fail for Special.")
    notes = warnings(state, check)
    target = required(check, len(ids))
    lines = [
        f"Check {ident}: {check['kind']} / {check['difficulty']}; original {len(check['cohort'])}, eligible {len(ids)}; requirement {target}."
    ]
    if check["kind"] == "special":
        lines.extend(
            (f"Requirement: {check['options']['requirement']}", f"Hint: {check['options']['hint']}")
        )
    lines.append(
        f"Failure damage per eligible target: {check['profile']['failure']}; Tank adds it only on complete Front collapse; Contest damages only individual failures."
    )
    lines.append(
        "Success: one nonstacking next-full-turn Stagger; Tank/Contest also deal proportional Backlash."
    )
    if check["kind"] == "tank":
        lines.append(
            "Tank profile: physical, Accuracy 0, Spirit 0; each Front automatically Resists; no paid reaction. Outcome is rolled only on commitment."
        )
        front = [member for member in ids if rules.position(state, member) == "front"]
        for index, member in enumerate(front):
            share = target // len(front) + (index < target % len(front))
            lines.append(
                f"  Front {state['participants'][member]['name']}: {share} declared damage before Resist, truncated to remaining Vitality."
            )
        lines.append(
            "Complete collapse adds the failure wave only to members still eligible after the test; incapacitated Front defenders are not damaged twice."
        )
    if check["kind"] in ("tank", "contest"):
        basis = target if check["kind"] == "tank" else len(ids) * number(check["profile"]["tank"])
        lines.append(
            f"Success Backlash: {(basis * number(check['profile']['backlash'])).__ceil__()} before remaining boss Vitality truncation."
        )
    elif check["kind"] == "dps":
        lines.append(f"Credited direct damage: {sum(check['damage'].values())}.")
    elif check["kind"] == "support":
        lines.append(f"Current final Party boost: {rules.boost(state, check['party'])}%.")
    elif check["kind"] == "pressure":
        lines.append(
            f"Current boss Spirit: {F(state['participants'][check['boss']]['spirit'], 100)}."
        )
    for member in check["cohort"]:
        row = state["participants"][member]
        initial = check["initial"][member]
        turns, partial = divmod(
            row["actions_spent"] - initial["actions_spent"], initial["allowance"]
        )
        lines.append(
            f"  {row['name']}: {turns} whole response turns + {partial}/{initial['allowance']} allowances; {row['clock'] - initial['clock']} exchanges; {budget(row)} actions left; {'withdrawn' if member in check['withdrawn'] else 'eligible' if member in ids else 'unavailable'}."
        )
    lines.extend(notes)
    token = fingerprint(state, ident, verdict)
    lines.append(f"Resolve with token {token}; acknowledge pacing warnings with a public reason.")
    return {"token": token, "warnings": notes, "lines": lines}


@atomic
def resolve(
    state, ident, token, *, verdict=None, acknowledgment="", draws=None, contest_available=True
):
    view = preview(state, ident, verdict=verdict, contest_available=contest_available)
    if token != view["token"]:
        raise CombatError("That Check preview is stale; preview the current state again.")
    if view["warnings"] and not acknowledgment.strip():
        raise CombatError("Acknowledge the Check warnings with a public reason before resolving.")
    check = deepcopy(get(state, ident))
    ids = eligible(state, check)
    n, kind = len(ids), check["kind"]
    threshold = required(check, n)
    front = [i for i in ids if rules.position(state, i) == "front"]
    get(state, ident)["status"] = "resolving"
    losses = {}
    passed, collapse = False, False
    failure = number(check["profile"]["failure"]).__ceil__()
    if kind == "tank":
        if set(front) - (draws or {}).keys():
            raise CombatError("Supply one committed Resist draw per Front defender.")
        for index, member in enumerate(front):
            share = threshold // len(front) + (index < threshold % len(front))
            outcome = effects.resist(
                state, check["boss"], member, share, draws[member], f"check/{ident}/tank/{member}"
            )
            losses[member] = outcome
        passed = bool(front) and all(state["participants"][i]["hp"] > 0 for i in front)
        collapse = not front or not any(
            engine.participating(state["participants"][i]) for i in front
        )
    elif kind == "dps":
        passed = sum(check["damage"].values()) >= threshold
    elif kind == "support":
        passed = rules.boost(state, check["party"]) >= threshold
    elif kind == "pressure":
        passed = state["participants"][check["boss"]]["spirit"] <= threshold
    elif kind == "special":
        passed = verdict
    else:
        passed = sum(bool(check["attempts"].get(i, {}).get("success")) for i in ids) >= threshold
        for member in ids:
            if not check["attempts"].get(member, {}).get("success"):
                losses[member] = effects.damage(
                    state, check["boss"], member, failure, f"check/{ident}/contest/{member}"
                )
    if (kind == "tank" and collapse) or (not passed and kind not in ("tank", "contest")):
        for member in ids:
            if engine.participating(state["participants"][member]):
                loss = effects.damage(
                    state, check["boss"], member, failure, f"check/{ident}/failure/{member}"
                )
                losses[f"failure/{member}"] = loss
    backlash = 0
    if passed:
        if kind in ("tank", "contest"):
            basis = threshold if kind == "tank" else n * number(check["profile"]["tank"])
            amount = (basis * number(check["profile"]["backlash"])).__ceil__()
            backlash = effects.damage(
                state, ids[0], check["boss"], amount, f"check/{ident}/backlash"
            )
        effects.stagger(
            state, check["boss"], int(number(conf.get("RP_PARTY_STAGGER_POINTS"))), ident
        )
    result = {
        "passed": bool(passed),
        "eligible": ids,
        "threshold": str(threshold),
        "collapse": collapse,
        "damage": losses,
        "backlash": backlash,
        "acknowledgment": acknowledgment,
    }
    get(state, ident).update(status="resolved", result=result)
    engine.settle(state)
    return deepcopy(result)


def lines(state):
    result = []
    for check in rules.data(state)["checks"].values():
        label = rules.data(state)["parties"][check["party"]]["name"]
        result.append(
            f"Boss Check {check['id']}: {check['kind']} / {check['difficulty']} -> {label}; {check['status']}; {len(eligible(state, check))}/{len(check['cohort'])} eligible."
        )
        if check["status"] == "pending":
            result.append(
                "  +bosscheck/withdraw cancels only your participation; /cancel cancels your Party's Check. Committed consequences require staff recovery."
            )
            if check["kind"] == "special":
                result.extend(
                    (
                        f"  Requirement: {check['options']['requirement']}",
                        f"  Hint: {check['options']['hint']}",
                    )
                )
            result.extend(f"  {note}" for note in warnings(state, check))
    return tuple(line[:500] for line in result)
