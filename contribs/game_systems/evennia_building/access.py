from django.conf import settings
from django.core.exceptions import PermissionDenied

from evennia_links.rooms import ACTIONS
from evennia_links.runtime import get

from .models import DraftRoom, GuestInvitation, Resident, RoomOverride, RoomOwnership


def is_staff(actor):
    expression = getattr(settings, "BUILDING_STAFF_LOCK", "perm(Builder)").removeprefix("cmd:")
    return bool(actor and actor.locks.check_lockstring(actor, expression))


def require_revealed(actor):
    if (
        not actor
        or not actor.pk
        or not actor.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False)
        or (not is_staff(actor) and not get("BUILDING_REVEALED"))
    ):
        raise PermissionDenied("Building is not available yet.")


def ownership(room):
    return (
        RoomOwnership.objects.select_related("property", "owner")
        .filter(object_id=getattr(room, "pk", None))
        .first()
    )


def owner_of(room):
    record = ownership(room)
    return record.owner if record and record.room_id and record.property.state == "live" else None


def room_permission(actor, room, action):
    if action not in ACTIONS or not actor or not room:
        return False
    record = ownership(room)
    if record:
        if not get("BUILDING_REVEALED") and not is_staff(actor):
            return False
        if (
            not record.room_id
            or not record.owner_id
            or record.property.owner_id != record.owner_id
            or not record.property.anchor_id
            or record.property.state != "live"
        ):
            return False
        if actor.pk == record.owner_id:
            return action != "transfer"
        return (
            action == "install"
            and _override_allows(record, actor)
            and Resident.objects.filter(
                property=record.property, character=actor, can_install=True
            ).exists()
        )
    draft = DraftRoom.objects.select_related("project").filter(object_id=room.pk).first()
    if draft:
        # Draft edits must version the proposal and preserve isolation flags.
        # Generic room commands do neither; author through Building services.
        return False
    return bool(room.access(actor, "control"))


def _override_allows(record, actor):
    override = RoomOverride.objects.filter(ownership=record).first()
    return override is None or bool(actor and actor.pk in override.allowed_character_ids)


def _granted(record, actor, scope):
    if not actor:
        return False
    return (
        Resident.objects.filter(property=record.property, character=actor).exists()
        or GuestInvitation.objects.filter(
            property=record.property, character=actor, state="accepted", **{scope: True}
        ).exists()
    )


def managed_access(room, actor, *, scope="entry", public_entry=False):
    """Three-way answer. None means the host retains its existing policy."""
    record = ownership(room)
    if record:
        if (
            not record.room_id
            or not record.owner_id
            or record.property.owner_id != record.owner_id
            or not record.property.anchor_id
            or record.property.state != "live"
        ):
            return False
        if is_staff(actor):
            return True
        if not get("BUILDING_REVEALED"):
            return False
        if actor and actor.pk == record.owner_id:
            return True
        if scope == "entry" and public_entry:
            from .attachments import passage_allows

            if passage_allows(room, actor):
                return True
        if not _override_allows(record, actor):
            return False
        return _granted(record, actor, scope) or bool(public_entry and not record.property.locked)
    draft = (
        DraftRoom.objects.select_related("project")
        .filter(object_id=getattr(room, "pk", None))
        .first()
    )
    if draft:
        return bool(
            draft.room_id
            and draft.project.state in {"draft", "submitted"}
            and actor
            and (
                is_staff(actor) or (get("BUILDING_REVEALED") and actor.pk == draft.project.owner_id)
            )
        )
    return None


def can_enter(actor, room):
    result = managed_access(room, actor, public_entry=True)
    return True if result is None else result


def can_teleport(actor, room):
    return managed_access(room, actor)
