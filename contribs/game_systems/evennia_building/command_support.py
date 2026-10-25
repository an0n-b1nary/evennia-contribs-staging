# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player command lookup, durable room drafts and exact-state confirmations."""

from django.core import signing
from django.core.exceptions import ValidationError
from evennia.objects.models import ObjectDB

from . import collaboration, services
from .models import DraftRoom

SALT = "building-player-confirmation-v1"
DRAFT_KEY = "building_room_draft"


def number(value):
    """Read one positive record reference, never a positional argument chain."""
    text = value.strip().removeprefix("#")
    if not text.isdecimal() or int(text) < 1:
        raise ValidationError("Choose one name or #number.")
    return int(text)


def select(queryset, value, field="name"):
    """Resolve an unambiguous record name or ID within an authorized queryset."""
    value = value.strip()
    if value.removeprefix("#").isdecimal():
        return queryset.get(pk=number(value))
    rows = list(queryset.filter(**{f"{field}__iexact": value})[:2])
    if len(rows) != 1:
        raise ValidationError("Choose one available name or #number.")
    return rows[0]


def context(actor):
    """Get the inspectable project and draft room where the character stands."""
    room = (
        DraftRoom.objects.select_related("project", "part__anchor__room")
        .filter(room_id=actor.db_location_id, project__state__in=["draft", "submitted"])
        .first()
    )
    if not room or not collaboration.can_inspect(actor, room.project):
        raise ValidationError("Stand in your project first. Use +build/enter <project>.")
    return room.project, room


def project(actor, value=""):
    """Read a project from explicit authorized selection or the current room."""
    return select(collaboration.visible_projects(actor), value) if value else context(actor)[0]


def character(actor, value):
    """Use the host's player search policy when selecting another character."""
    found = actor.search(value.strip(), global_search=True, quiet=True, use_dbref=True)
    found = [
        obj
        for obj in found
        if obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False)
    ]
    if len(found) != 1:
        raise ValidationError("Choose one existing character by name or #number.")
    return found[0]


def draft_room(project, value):
    """Resolve an actual room name or object dbref, scoped to this project."""
    rows = project.rooms.select_related("room", "part__anchor__room").filter(room__isnull=False)
    if value.strip().removeprefix("#").isdecimal():
        return rows.get(object_id=number(value))
    matches = list(rows.filter(room__db_key__iexact=value.strip())[:2])
    if len(matches) != 1:
        raise ValidationError("Choose one room name or room #number in this project.")
    return matches[0]


def world_room(actor, value):
    """Select a room without exposing a private directory to the player."""
    from evennia_links.travel import room_visibility as host_visibility

    from .access import can_enter, is_staff, managed_access
    from .visibility import room_visibility

    rows = ObjectDB.objects.filter(db_location__isnull=True, db_destination__isnull=True)
    if value.strip().removeprefix("#").isdecimal():
        rows = rows.filter(pk=number(value))
    else:
        rows = rows.filter(db_key__iexact=value.strip())

    def accessible(room):
        if actor.db_location_id == room.pk or is_staff(actor):
            return True
        visible = host_visibility(room, actor)
        if managed_access(room, actor) is not None:
            return can_enter(actor, room) or room_visibility(room, actor)
        return visible is not False and services._read_attr(room, "allow_teleport") not in {
            "secret",
            "private",
        }

    matches = [
        room
        for room in rows
        if room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        and accessible(room)
    ]
    if len(matches) != 1:
        raise ValidationError("Choose one accessible room name or #number.")
    return matches[0]


def confirm(actor, action, state, token):
    """Create a preview token, or verify the actor, action and current state."""
    expected = {"actor": actor.pk, "action": action, "state": services.fingerprint(state)}
    if not token:
        return signing.dumps(expected, salt=SALT, compress=True)
    try:
        received = signing.loads(token, salt=SALT, max_age=900)
    except signing.BadSignature as exc:
        raise ValidationError("Invalid or expired token. Request a fresh preview.") from exc
    if received != expected:
        raise ValidationError("The candidate, agreement or owner changed. Request a fresh preview.")
    return None


def token_reason(value):
    """Read an optional token and a trailing reason, including a preview's bare reason."""
    if value.startswith("# "):
        return "", value[2:].strip()
    token, _, reason = value.partition(" # ")
    return token.strip(), reason.strip()


def candidate_text(candidate):
    """Show the complete reviewed content as readable text rather than JSON."""
    lines = [
        f"{candidate['name']} — {candidate.get('kind', 'interior')}, {candidate['purpose']}",
        f"Proposed owner #{candidate['owner']}; anchor #{candidate['anchor']}; entrance {candidate['entrance']}",
        f"Environment inherited: terrain {candidate['terrain']}; region {candidate['region']}",
        f"Environment requested: {candidate['requested_environment']}",
    ]
    for room in candidate["rooms"]:
        lines.extend(
            [
                f"Room #{room['id']}: {room['name']} (floor {room['floor']}, x {room['x']}, y {room['y']})",
                room["description"] or "No description.",
                f"Mood: {room['mood'] or 'none'}",
            ]
        )
    for door in candidate["doors"]:
        lines.append(
            f"Door #{door['id']}: {door['name']} (#{door['source']} to #{door['target']}); "
            f"aliases {', '.join(door['aliases']) or 'none'}"
        )
    for part in candidate.get("parts", []):
        lines.append(
            f"Interior {part['id']}: {part['name']}; owner #{part['owner']}; {part['purpose']}; "
            f"anchor #{part['anchor']}; entrance {part['entrance']}; rooms {part['rooms']}"
        )
    for connection in candidate.get("connections", []):
        lines.append(
            f"Grid connection: #{connection['source']} to #{connection['target']} "
            f"({connection['direction']})"
        )
    attachment = candidate.get("attachment")
    if attachment:
        lines.append(
            f"Parent property {attachment['parent']}; owner #{attachment['parent_owner']}; "
            f"passage {attachment['route']['rooms']}"
        )
    lines.extend(candidate["report"]["warnings"])
    return "\n".join(lines)


def room_draft(actor):
    """Read a persistent draft while checking its original context and version."""
    data = actor.attributes.get(DRAFT_KEY)
    if not data:
        raise ValidationError("Start a room draft with +build/dig <name>.")
    data = dict(data)
    obj, source = context(actor)
    if data["project"] != obj.pk or data["source"] != source.pk:
        raise ValidationError("Return to the room where you started this draft, or +build/cancel.")
    if data["version"] != obj.version:
        raise ValidationError("The project changed. Cancel this room draft and start again.")
    return data, obj, source


def save_room_draft(actor, data):
    """Persist a room plan across reloads; it is private to the author."""
    actor.attributes.add(DRAFT_KEY, data)
