# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authorized Party operations through combat's locked, journaled coordinator."""

from evennia.objects.models import ObjectDB
from evennia_rp_combat import conf as combat_conf
from evennia_rp_combat import engine, partners
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import CombatError

from evennia_links import runtime

from . import conf, providers, rules


def require(actor, *, progress=False):
    combat.require(actor, progress=progress)
    if not runtime.get("RP_PARTY_REVEALED"):
        raise CombatError("Parties are not available yet.")
    if "party" not in partners.registered():
        raise CombatError("Register the Party provider before using Party commands.")
    if progress and runtime.get("RP_PARTY_FROZEN"):
        raise CombatError("Party coordination is frozen; inspection, chat and cleanup remain.")


def change(
    actor, operation, argument="", *, subject=None, cover=None, target=None, operation_id=None
):
    subject = subject or actor
    cleanup = operation in ("rename", "dissolve", "agree", "decline_dissolve", "decline")
    require(actor, progress=not cleanup)
    combat.authorize(actor, subject, cleanup=cleanup)

    def apply(state):
        engine.participant(state, subject.pk)
        if operation == "create":
            result = rules.create(state, subject.pk, combat.plain(argument, 61))
        elif operation == "join":
            rules.join(state, subject.pk, argument)
            result = argument
        elif operation == "accept":
            invitation = rules.data(state)["invitations"].get(str(subject.pk))
            if not invitation:
                raise CombatError("No Party invitation is pending.")
            inviter = ObjectDB.objects.filter(pk=invitation["by"]).first()
            if inviter is not None:
                combat.interaction(subject, inviter)
            result = invitation["party"]
            rules.join(state, subject.pk, result)
        elif operation == "decline":
            if not rules.data(state)["invitations"].pop(str(subject.pk), None):
                raise CombatError("No Party invitation is pending.")
            result = "declined"
        elif operation == "leave":
            rules.leave(state, subject.pk)
            result = "unpartied"
        elif operation == "formation":
            rules.formation(state, subject.pk, argument, cover=cover)
            result = argument
            if argument == "back":
                permission = "on" if rules.member(state, subject.pk).get("cover") else "off"
                combat.notice(
                    state,
                    f"Back-row Cover is {permission}; use +party/formation back=on or =off to choose. It permits same-party Front members to take an unaccepted attack.",
                )
        elif operation == "rename":
            rules.rename(state, subject.pk, combat.plain(argument, 61))
            result = argument
        elif operation == "invite":
            if target is None or target.location != actor.location:
                raise CombatError("Invite an enrolled ally in this room.")
            combat.interaction(subject, target)
            row = engine.participant(state, target.pk)
            key = rules.party_id(state, subject.pk)
            if not key or rules.party(state, key)["side"] != row["side"]:
                raise CombatError("Invite an ally on your party's side.")
            rules.data(state)["invitations"][str(target.pk)] = {"party": key, "by": str(subject.pk)}
            result = key
            combat.notice(
                state,
                f"{target.key} may +party/accept; their fight entry and current membership are unchanged.",
            )
        elif operation in ("dissolve", "agree", "decline_dissolve"):
            key = argument or rules.party_id(state, subject.pk)
            result = rules.dissolve(
                state,
                subject.pk,
                key,
                agree=operation == "agree",
                decline=operation == "decline_dissolve",
            )
        else:
            raise CombatError("Unknown Party operation. See help +party.")
        combat.notice(state, f"Party {operation}: {combat.plain(result)}.")
        return result

    return combat.execute(
        actor,
        f"{combat.identity(subject)} used Party {operation} {combat.plain(argument)}",
        apply,
        progressing=not cleanup,
        subject=subject,
        operation_id=operation_id,
    )


def cover(
    actor,
    original,
    token,
    kind="resist",
    *,
    subject=None,
    counter="balanced",
    empower=False,
    domain="",
    operation_id=None,
    preview=False,
):
    subject = subject or actor
    require(actor, progress=True)
    combat.authorize(actor, subject)

    def apply(state):
        if original.location != actor.location:
            raise CombatError("The original defender has left the room.")
        exchange = rules.cover_allowed(state, str(subject.pk), str(original.pk), token)
        attacker = ObjectDB.objects.filter(pk=exchange["actor"]).first()
        if attacker is None or attacker.location != actor.location:
            raise CombatError("The attacker has left; cancel the unaccepted attack instead.")
        combat.interaction(subject, original)
        combat.interaction(subject, attacker)
        row = engine.participant(state, subject.pk)
        penalty = (
            conf.get("RP_PARTY_PINPOINT_PENALTY")
            if exchange["domain_effect"] == "pinpoint"
            and not engine.blocks(row, exchange["domain"], "pinpoint")
            else "0"
        )
        chosen = (
            combat.choose_move(row, engine.available_armed(state, row).get("counter", counter))
            if kind == "overpower"
            else None
        )
        if preview:
            view = engine.interception_view(
                state, token, original.pk, subject.pk, reaction_penalty=penalty
            )
            return combat.describe_odds(view, token)
        engine.redirect(
            state,
            token,
            original.pk,
            subject.pk,
            kind,
            counter=chosen,
            empower=empower,
            domain=domain,
            domain_effects=combat_conf.get("RP_COMBAT_DOMAIN_EFFECTS"),
            reaction_penalty=penalty,
        )
        return token

    if preview:
        return apply(combat.state_for(actor))
    return combat.execute(
        actor,
        f"{combat.identity(subject)} Covered {combat.identity(original)} with {combat.plain(kind)} for {combat.plain(token)}",
        apply,
        subject=subject,
        operation_id=operation_id,
    )


def render(actor, *, subject=None):
    subject = subject or actor
    require(actor)
    combat.authorize(actor, subject, cleanup=True)
    state = combat.state_for(actor)
    return "\n".join(combat.plain(line, 500) for line in providers.status(state, str(subject.pk)))


def surge(actor, targets, key="balanced", *, boosted=None, subject=None, **options):
    """Declare and reserve in combat's one transaction, including auto-reactions."""
    require(actor, progress=True)
    if not targets:
        raise CombatError("Name at least one target for Team Surge.")
    boosted = boosted or targets[0]
    if boosted not in targets:
        raise CombatError("The Team Surge target must be one of the declared targets.")
    return combat.declare(
        actor,
        targets,
        key,
        subject=subject,
        partner_requests={"party": {"kind": "surge", "target": str(boosted.pk)}},
        **options,
    )


def surge_press(actor, *, subject=None, empower=False, rng=None, operation_id=None):
    require(actor, progress=True)
    return combat.control(
        actor,
        "press",
        subject=subject,
        argument="empower" if empower else "",
        partner_requests={"party": {"kind": "surge", "target": ""}},
        rng=rng,
        operation_id=operation_id,
    )


def chat(actor, message, *, subject=None):
    """Transient OOC routing only: never execute/journal or call a posing hook."""
    from evennia_links.communication import denial

    blocked = denial(actor, "ooc")
    if blocked:
        raise CombatError(blocked)
    subject = subject or actor
    require(actor)
    combat.authorize(actor, subject, cleanup=True)
    state = combat.state_for(actor)
    engine.participant(state, subject.pk)
    key = rules.party_id(state, subject.pk)
    if not key:
        raise CombatError("Join a party before using party OOC chat.")
    message = combat.plain(message, 2000).strip()
    if not message:
        raise CombatError("Write an OOC message.")
    text = f"[Party OOC: {rules.party(state, key)['name']}] {combat.identity(subject)}: {message}"
    delivered = set()
    for recipient in ObjectDB.objects.filter(
        pk__in=rules.roster(state, key), db_location=actor.location
    ):
        controller = combat.owner(recipient)
        account = combat.account(recipient)
        if (
            controller is None
            or account is None
            or account.pk in delivered
            or not account.is_connected
        ):
            continue
        if combat.ignored_by(recipient, subject) or combat.ignored_by(subject, recipient):
            continue
        controller.msg(text, options={"type": "party_ooc"})
        delivered.add(account.pk)
    return len(delivered)
