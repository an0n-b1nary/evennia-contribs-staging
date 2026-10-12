# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Party rules over saved combat state only; no models, presence or randomness."""

from copy import deepcopy
from fractions import Fraction as F

from evennia_rp_combat import engine
from evennia_rp_combat.data import CombatError
from evennia_rp_combat.partners import number

from . import conf

POSITIONS = ("front", "back", "flex")


def upgrade(section):
    if section is None:
        return {
            "schema": 1,
            "data": {
                "next_party": 1,
                "parties": {},
                "members": {},
                "invitations": {},
                "support": {},
                "pending_support": {},
                "proposals": {},
            },
        }
    if section.get("schema") != 1:
        raise CombatError("Unsupported Party state version; no progress was applied.")
    result = deepcopy(section)
    data = result["data"]
    if (
        type(data.get("next_party")) is not int
        or data["next_party"] < 1
        or any(
            not isinstance(data.get(key), dict)
            for key in (
                "parties",
                "members",
                "invitations",
                "support",
                "pending_support",
                "proposals",
            )
        )
    ):
        raise CombatError("Invalid saved Party state.")
    return result


def data(state):
    try:
        return state["partners"]["party"]["data"]
    except KeyError:
        raise CombatError("The Party provider is not registered for this fight.") from None


def party(state, key):
    row = data(state)["parties"].get(str(key))
    if row is None or row["dissolved"]:
        raise CombatError("Choose an existing party identity from +party.")
    return row


def member(state, ident):
    return data(state)["members"].get(str(ident), {})


def party_id(state, ident):
    return member(state, ident).get("party")


def roster(state, key):
    return [
        ident
        for ident, row in data(state)["members"].items()
        if row.get("party") == key and ident in state["participants"]
    ]


def counted(state, key):
    return [
        ident for ident in roster(state, key) if engine.participating(state["participants"][ident])
    ]


def position(state, ident):
    return member(state, ident).get("position", "flex") if party_id(state, ident) else "flex"


def protected(state, ident):
    key = party_id(state, ident)
    return bool(
        key
        and position(state, ident) == "back"
        and any(position(state, other) == "front" for other in counted(state, key))
    )


def average(state, key):
    ids = counted(state, key)
    # Engine hundredths become displayed Spirit points exactly here.
    return (
        F(sum(state["participants"][ident]["spirit"] for ident in ids), 100 * len(ids))
        if ids
        else F(0)
    )


def finished(row):
    return row["hp"] <= 0 or row["status"] == "withdrawn" or row["turns"] >= row["turn_limit"]


def expired(state, source, entry):
    """Saved clocks also expire support after progress with the owner absent."""
    row = state["participants"][source]
    if row["clock"] > entry.get("source_clock", row["clock"]):
        return True
    return finished(row) and any(
        ident in state["participants"]
        and party_id(state, ident) == entry["party"]
        and state["participants"][ident]["clock"] > clock
        for ident, clock in entry.get("party_clocks", {}).items()
    )


def boost(state, key):
    if not key or not counted(state, key):
        return F(0)
    value = average(state, key) * number(conf.get("RP_PARTY_SPIRIT_COEFFICIENT"))
    for source, entry in data(state)["support"].items():
        if (
            entry["party"] == key
            and source in state["participants"]
            and engine.participating(state["participants"][source])
            and not expired(state, source, entry)
        ):
            value += number(entry["points"]) * (1 if entry["kind"] == "rally" else -1)
    return max(F(0), min(number(conf.get("RP_PARTY_BOOST_CAP")), value))


def name(state, value, *, excluding=None):
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= 60
        or any(ord(char) < 32 for char in value)
    ):
        raise CombatError("Choose a party name of 1..60 printable characters.")
    value = value.strip()
    if any(
        key != excluding and not row["dissolved"] and row["name"].casefold() == value.casefold()
        for key, row in data(state)["parties"].items()
    ):
        raise CombatError("That party name is already in use here.")
    return value


def clear_queue(state, ident):
    row = engine.participant(state, ident)
    if row["incoming"] or row["outgoing"]:
        raise CombatError("Finish every affected incoming and outgoing exchange first.")
    return row


def create(state, ident, value):
    engine.progress(state)
    row = clear_queue(state, ident)
    if party_id(state, ident):
        raise CombatError("Leave your current party before creating another.")
    key = prepare(state, value, row["side"])
    join(state, ident, key)
    return key


def prepare(state, value, side):
    """Host-authored empty party; player commands additionally require enrollment."""
    section = data(state)
    value = name(state, value)
    key = f"{state['epoch']}.{section['next_party']}"
    section["next_party"] += 1
    section["parties"][key] = {"name": value, "side": side, "dissolved": False}
    return key


def join(state, ident, key):
    engine.progress(state)
    row = clear_queue(state, ident)
    selected = party(state, key)
    if selected["side"] != row["side"]:
        raise CombatError("A party belongs to one side; joining never changes sides.")
    previous = party_id(state, ident)
    if previous == str(key):
        raise CombatError("You already belong to that party.")
    for affected in (previous, str(key)):
        data(state)["proposals"].pop(affected, None)
    data(state)["members"][str(ident)] = {"party": str(key), "position": "flex", "cover": False}
    data(state)["invitations"].pop(str(ident), None)


def leave(state, ident):
    engine.progress(state)
    clear_queue(state, ident)
    key = party_id(state, ident)
    if not key:
        raise CombatError("You are already unpartied.")
    data(state)["members"][str(ident)] = {
        "party": None,
        "last_party": key,
        "position": "flex",
        "cover": False,
    }
    data(state)["proposals"].pop(key, None)


def formation(state, ident, value, *, cover=None):
    engine.progress(state)
    clear_queue(state, ident)
    if not party_id(state, ident) or value not in POSITIONS:
        raise CombatError("Join a party and choose Front, Back or Flex.")
    row = member(state, ident)
    row["position"] = value
    if cover is not None:
        if type(cover) is not bool:
            raise CombatError("Cover permission must be explicitly on or off.")
        row["cover"] = cover


def rename(state, ident, value):
    key = party_id(state, ident)
    if not key:
        raise CombatError("Only a current member can rename a party.")
    party(state, key)["name"] = name(state, value, excluding=key)


def dissolve(state, ident, key, *, agree=False, decline=False):
    engine.participant(state, ident)
    party(state, key)
    ids = roster(state, key)
    required = set(counted(state, key))
    section = data(state)
    if decline:
        if str(ident) not in ids:
            raise CombatError("Only members may decline dissolution.")
        section["proposals"].pop(key, None)
        return "declined"
    if required:
        if str(ident) not in ids:
            raise CombatError("Only members may propose or agree to dissolution.")
        if agree and key not in section["proposals"]:
            raise CombatError("No dissolution proposal is pending.")
        proposal = section["proposals"].setdefault(key, {"yes": []})
        if str(ident) not in proposal["yes"]:
            proposal["yes"].append(str(ident))
        if not required <= set(proposal["yes"]):
            return "waiting for members' agreement"
    for other in ids:
        clear_queue(state, other)
    for other in ids:
        section["members"][other] = {
            "party": None,
            "last_party": key,
            "position": "flex",
            "cover": False,
        }
    party(state, key)["dissolved"] = True
    section["support"] = {
        source: entry for source, entry in section["support"].items() if entry["party"] != key
    }
    section["pending_support"] = {
        ex: entry for ex, entry in section["pending_support"].items() if entry["party"] != key
    }
    section["invitations"] = {
        target: entry for target, entry in section["invitations"].items() if entry["party"] != key
    }
    section["proposals"].pop(key, None)
    return "dissolved"


def cover_allowed(state, coverer, original, token):
    engine.active(state, coverer)
    engine.active(state, original)
    key = party_id(state, original)
    exchange = engine.get_exchange(state, token)
    if (
        not key
        or party_id(state, coverer) != key
        or position(state, coverer) != "front"
        or position(state, original) != "back"
        or not member(state, original).get("cover")
        or exchange["move"]["action"] not in ("attack", "spell")
    ):
        raise CombatError("Cover needs a same-party Front and an opted-in Back defender.")
    return exchange
