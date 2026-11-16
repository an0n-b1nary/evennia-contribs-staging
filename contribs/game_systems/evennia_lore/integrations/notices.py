# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authoritative Lore visibility and historical decision presentation."""

from django.utils.dateparse import parse_datetime

from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeAction,
    NoticeEvent,
    RenderedNotice,
    SubjectRef,
    authorize_context,
)


def event_for(row):
    """Reconstruct exactly the immutable source-owned event."""
    data = row.envelope
    return NoticeEvent(
        data["event_id"],
        parse_datetime(data["occurred_at"]),
        SubjectRef(**data["subject"]),
        tuple(ActorRef(**actor) for actor in data["actors"]),
        data["payload"],
    )


def subject_status(entry, character, payload, *, held=None, staff=None):
    """Check live subject and original recipient role independently of transport."""
    from evennia_lore.commands import is_staff
    from evennia_lore.models import LoreAcquisition, LoreEntry

    if (
        entry is None
        or entry.is_archived
        or entry.status != LoreEntry.Status.PUBLISHED
        or payload.get("entry") != entry.pk
        or payload.get("recipient") != character.pk
    ):
        return Evaluation("invalid")
    if held is None:
        held = LoreAcquisition.objects.filter(entry=entry, character=character).exists()
    if payload.get("kind") in {"affirmed", "declined"}:
        if payload.get("author") != character.pk or entry.author_id != character.pk:
            return Evaluation("invalid")
    elif payload.get("kind") == "unsealed":
        if not held:
            return Evaluation("invalid")
    else:
        return Evaluation("defer", reason="provenance")
    if (
        entry.privacy != LoreEntry.Privacy.PUBLIC
        and not held
        and not (is_staff(character) if staff is None else staff)
    ):
        return Evaluation("invalid")
    return Evaluation("visible")


def render_payload(payload):
    """Use historical snapshots, never a later mutable decline note."""
    title, number = payload["title"], payload["number"]
    kind = payload["kind"]
    if kind == "affirmed":
        text = f"Staff affirmed your lore entry {title} (#{number})."
    elif kind == "declined":
        text = f"Staff declined to affirm {title} (#{number}): {payload['note']}"
    else:
        text = f"New light on {title} (#{number}): its OOC notes have been unsealed."
    return RenderedNotice(
        text,
        (
            NoticeAction(
                "Read lore",
                command=f"+lore/read #{number}",
                route_name="lore-detail",
                route_args=(payload["entry"],),
            ),
        ),
    )


class LoreNoticeSource:
    """Character-owned dismissible Lore decisions with recheckable provenance."""

    label = "Lore"

    def prepare(self, context):
        """Import one bounded page only for the actual selected character."""
        if context.character is not None and authorize_context(context, context.character):
            from evennia_lore.notices import transfer_pending

            transfer_pending(context.character, context=context)

    def evaluate(self, events, context):
        """Reject forged envelopes and denied subjects before text or counts."""
        from evennia_lore.commands import is_staff
        from evennia_lore.models import LoreAcquisition, LoreNotice

        ids = {e.payload.get("notice") for e in events if type(e.payload.get("notice")) is int}
        rows = LoreNotice.objects.filter(pk__in=ids).select_related("entry", "character").in_bulk()
        selected = context.character
        authorized = selected is not None and authorize_context(context, selected)
        held = (
            set(
                LoreAcquisition.objects.filter(
                    character=selected, entry_id__in=[r.entry_id for r in rows.values()]
                ).values_list("entry_id", flat=True)
            )
            if selected is not None
            else set()
        )
        staff = is_staff(selected) if selected is not None else False
        outcomes = {}
        for event in events:
            row = rows.get(event.payload.get("notice"))
            try:
                if row is None:
                    outcome = Evaluation("invalid")
                elif not row.provenance_known or row.kind not in {
                    "affirmed",
                    "declined",
                    "unsealed",
                }:
                    outcome = Evaluation("defer", reason="provenance")
                else:
                    expected = event_for(row)
                    same = (
                        event.recipient_kind == "character"
                        and event.recipient_id == row.character_id
                        and all(
                            getattr(event, name) == getattr(expected, name)
                            for name in expected.__dict__
                        )
                    )
                    if not same:
                        outcome = Evaluation("invalid")
                    elif context.character != row.character or not authorized:
                        outcome = Evaluation("defer", reason="context")
                    else:
                        outcome = subject_status(
                            row.entry,
                            row.character,
                            event.payload,
                            held=row.entry_id in held,
                            staff=staff,
                        )
            except (KeyError, ValueError, TypeError):
                outcome = Evaluation("defer", reason="provenance")
            outcomes[event.event_id] = outcome
        return outcomes

    def render(self, events, context):
        """Render only already-authorized immutable constituents."""
        if len(events) > 1:
            return RenderedNotice(
                f"{len(events)} Lore decisions or changes. Check your lore alerts."
            )
        return render_payload(events[0].payload)
