"""Reversible staff retirement and character-specific quiet review."""

from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.module_loading import import_string
from evennia.objects.models import ObjectDB

from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from .access import can_enter, is_staff, ownership, require_revealed
from .attachments import begin_write, lock_properties, route_snapshot
from .models import AttachmentAgreement, BuildingClock, Property, QuietFlag
from .policy import resolve_policy


def _staff(actor):
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied(
            "Only Building staff may archive, restore or review quiet properties."
        )


@atomic_objects
def archive(actor, property, *, reason, include_children=False):
    from .services import _changed, _exit_data, _safe_room, _text

    begin_write()
    _staff(actor)
    reason = _text(reason, 10000)
    if type(include_children) is not bool:
        raise ValidationError(
            "Explicitly choose whether affected apartments are archived together."
        )
    room_ids = property.rooms.values_list("object_id", flat=True)
    children = list(
        Property.objects.filter(anchor_id__in=room_ids, state="live").exclude(pk=property.pk)
    )
    lock_properties([property.pk, *(child.pk for child in children)])
    property = Property.objects.get(pk=property.pk)
    if property.state == "archived":
        return property
    if property.state != "live":
        raise ValidationError("This property needs staff repair.")
    children = list(
        Property.objects.filter(anchor_id__in=room_ids, state="live").exclude(pk=property.pk)
    )
    lock_properties([child.pk for child in children])
    children = list(
        Property.objects.filter(anchor_id__in=room_ids, state="live").exclude(pk=property.pk)
    )
    if children and not include_children:
        raise ValidationError(
            "Archival would strand active apartments. Arrange replacement passage or explicitly archive the affected properties together."
        )
    # Snapshot/check every entrance before any relocation or mutation.
    targets = [*children, property]
    child_room_ids = [
        pk for child in children for pk in child.rooms.values_list("object_id", flat=True)
    ]
    if (
        Property.objects.filter(anchor_id__in=child_room_ids, state="live")
        .exclude(pk__in=[target.pk for target in targets])
        .exists()
    ):
        raise ValidationError(
            "Archive deeper legacy properties separately first; active homes must not be stranded."
        )
    for target in targets:
        if not target.entrance or not target.departure or not target.anchor_id:
            raise ValidationError("An entrance or anchor is missing; repair it before archival.")
        if target.entrance.db_location_id != target.anchor_id:
            raise ValidationError("An entrance moved; repair it before archival.")
    room_ids = set()
    for target in targets:
        room_ids.update(target.rooms.values_list("object_id", flat=True))
    occupants = list(ObjectDB.objects.filter(db_location_id__in=room_ids))
    relocation = []
    parent_agreement = (
        AttachmentAgreement.objects.filter(child=property).select_related("parent").first()
    )
    for obj in occupants:
        if obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False):
            destination = parent_agreement.parent.anchor if parent_agreement else property.anchor
            if not destination or destination.pk in room_ids or not can_enter(obj, destination):
                destination = _safe_room(obj, room_ids)
            relocation.append((obj, destination))
    for obj, destination in relocation:
        obj.location = destination
    for target in targets:
        agreement = AttachmentAgreement.objects.filter(child=target).first()
        target.archive_data = {
            "entrance": _exit_data(target.entrance),
            "departure": _exit_data(target.departure),
            "anchor": target.anchor_id,
            "anchor_owner": getattr(ownership(target.anchor), "owner_id", None),
            "owner": target.owner_id,
            "parent_owner": agreement.parent.owner_id if agreement else None,
            "route": agreement.route if agreement else None,
            "group": [row.pk for row in targets],
        }
        target.entrance.location = None
        target.state = "archived"
        target.save(update_fields=["state", "archive_data"])
        QuietFlag.objects.filter(property=target, resolved_at__isnull=True).update(
            resolved_at=timezone.now()
        )
        _changed(
            target,
            actor,
            "archived",
            reason=reason,
            group=target.archive_data["group"],
            returned=[obj.pk for obj, _ in relocation],
        )
    return property


@atomic_objects
def restore(actor, property, *, reason):
    from .services import _changed, _exit_data, _read_attr, _text

    begin_write()
    _staff(actor)
    reason = _text(reason, 10000)
    agreement = AttachmentAgreement.objects.filter(child=property).first()
    lock_properties([property.pk, *([agreement.parent_id] if agreement else [])])
    property = Property.objects.get(pk=property.pk)
    if property.state == "live":
        return property
    if property.state != "archived" or not property.archive_data or not property.owner_id:
        raise ValidationError("This property needs staff repair before restore.")
    saved = property.archive_data
    anchor = ObjectDB.objects.select_for_update().filter(pk=property.anchor_id).first()
    if (
        not anchor
        or anchor.pk != saved["anchor"]
        or anchor.location
        or anchor.destination
        or not anchor.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        or _read_attr(anchor, "room_type", "ic") != "ic"
        or _read_attr(anchor, "allow_teleport") == "secret"
    ):
        raise ValidationError("The original attachment is unavailable; staff repair is required.")
    if resolve_policy(anchor) == "closed":
        raise ValidationError("The current attachment policy is closed.")
    if set(_read_attr(anchor, "terrain_tags", []) or []) & set(
        getattr(settings, "BUILDING_STAFF_ONLY_TERRAINS", ())
    ):
        raise ValidationError("The attachment has staff-only terrain.")
    if not property.entrance or not property.departure:
        raise ValidationError("The preserved entrance/departure needs repair.")
    actual = _exit_data(property.entrance)
    expected = {**saved["entrance"], "source": None}
    if actual != expected or _exit_data(property.departure) != saved["departure"]:
        raise ValidationError("The preserved connection changed; staff repair is required.")
    if (
        property.rooms.filter(room__isnull=True).exists()
        or not property.rooms.exists()
        or property.rooms.exclude(owner_id=property.owner_id).exists()
    ):
        raise ValidationError("The room ownership set needs repair.")
    for door in property.promotion.project.doors.filter(
        source__object_id__in=property.rooms.values_list("object_id", flat=True)
    ).select_related("exit", "source", "target"):
        data = _exit_data(door.exit) if door.exit_id else {}
        if (
            not door.exit_id
            or data["source"] != door.source.room_id
            or data["target"] != door.target.room_id
        ):
            raise ValidationError(
                "An internal door changed; repair usable interior access before restore."
            )
    exits = ObjectDB.objects.filter(db_location=anchor, db_destination__isnull=False)
    name = saved["entrance"]["name"].casefold()
    if any(
        name in {data["name"].casefold(), *(alias.casefold() for alias in data["aliases"])}
        for exit in exits
        for data in [_exit_data(exit)]
    ):
        raise ValidationError("The entrance name is already in use.")
    if get("BUILDING_DOOR_LIMIT_HARD") and exits.count() + 1 > get("BUILDING_DOOR_LIMIT"):
        raise ValidationError("The attachment reached its hard door limit.")
    if agreement:
        agreement = AttachmentAgreement.objects.select_related("parent", "child").get(
            pk=agreement.pk
        )
        if agreement.parent.state != "live":
            raise ValidationError("Restore the parent before its apartment.")
        route = route_snapshot(agreement.parent, agreement.route["rooms"], property.anchor_id)
        if route != agreement.route:
            raise ValidationError(
                "The passage changed; obtain fresh agreement to replacement passage."
            )
        owners_changed = (
            agreement.parent.owner_id != saved["parent_owner"]
            or property.owner_id != saved["owner"]
        )
        if (
            owners_changed
            and not agreement.changes.filter(
                state="applied",
                parent_owner=agreement.parent.owner,
                child_owner=property.owner,
                created_at__gte=property.audit.filter(action="archived")
                .latest("created_at")
                .created_at,
            ).exists()
        ):
            raise ValidationError(
                "Ownership changed since archival; obtain fresh passage agreement from both current owners."
            )
    else:
        anchor_record = ownership(anchor)
        if anchor_record and not (
            anchor_record.owner_id == property.owner_id == saved.get("anchor_owner")
            and anchor_record.property.state == "live"
        ):
            raise ValidationError(
                "The attachment acquired a property boundary; formal passage agreement is required."
            )
    property.entrance.location = anchor
    property.state = "live"
    property.save(update_fields=["state"])
    _changed(property, actor, "restored", reason=reason)
    return property


def last_played(character):
    """Default character hook timestamp. Accounts and web logins are irrelevant."""
    return character.attributes.get("building_last_played") if character else None


def activity(character):
    provider = getattr(
        settings, "BUILDING_ACTIVITY_PROVIDER", "evennia_building.lifecycle.last_played"
    )
    value = import_string(provider)(character)
    if value is None:
        return None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValidationError("The activity provider must return an aware datetime or None.")
    return value


@atomic_objects
def check_quiet(*, now=None):
    """Deduplicate notices; this never changes ownership, access or lifecycle."""
    begin_write()
    now = now or timezone.now()
    if not get("BUILDING_REVEALED"):
        return []
    clock, _ = BuildingClock.objects.get_or_create(pk=1, defaults={"revealed_at": now})
    cutoff = now - timedelta(days=get("BUILDING_QUIET_DAYS"))
    flagged = []
    for property in Property.objects.filter(state="live").select_related("owner"):
        lock_properties([property.pk])
        property.refresh_from_db()
        if property.state != "live":
            continue
        owner = property.owner
        seen = activity(owner) if owner else None
        online = bool(owner and owner.sessions.count())
        active = max(
            clock.revealed_at, property.created_at, seen or datetime.min.replace(tzinfo=UTC)
        )
        pending = QuietFlag.objects.filter(property=property, resolved_at__isnull=True)
        if online or active > cutoff:
            pending.update(resolved_at=now)
            continue
        reason = "quiet" if owner else "missing_owner"
        flag, _ = QuietFlag.objects.get_or_create(
            property=property,
            resolved_at__isnull=True,
            defaults={"owner_object_id": property.owner_id, "last_played": seen, "reason": reason},
        )
        flagged.append(flag)
    return flagged


def quiet_list(actor):
    _staff(actor)
    return QuietFlag.objects.filter(resolved_at__isnull=True).select_related("property")
