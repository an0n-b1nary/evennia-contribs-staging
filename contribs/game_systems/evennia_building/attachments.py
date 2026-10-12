"""Exact-candidate consent and durable, single-parent apartment passage."""

from itertools import pairwise

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models import F, Q
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.transactions import atomic_objects

from .access import can_enter, is_staff, managed_access, ownership, require_revealed
from .models import AttachmentAgreement, AttachmentConsent, BuildProject, PassageChange, Property

WORDING_VERSION = "1"
WORDING = (
    "I consent to this exact apartment proposal and the named passage route. "
    "After approval, the apartment owner independently controls their home and guests. "
    "I cannot lock the agreed passage rooms against that owner, their residents, or "
    "any guest they admit. This grants passage only, not access to other parent rooms, "
    "floor plans, occupants, editing or installation rights. Only staff may change "
    "an established route, with both affected owners' agreement to replacement passage. "
    "I may revoke this consent before promotion. Parent ownership transfer preserves passage."
)


def begin_write():
    # Acquire SQLite's writer reservation before *any* reads, including runtime
    # settings. Otherwise a competing commit leaves a read snapshot that cannot
    # be upgraded to a writer. PostgreSQL uses the domain row locks below.
    if connection.vendor == "sqlite":
        Property.objects.filter(pk=0).update(locked=F("locked"))


def lock_properties(ids):
    # Write first on SQLite as well; all access/lifecycle services share these rows.
    for pk in sorted(set(ids)):
        Property.objects.filter(pk=pk).update(locked=F("locked"))
        Property.objects.select_for_update().get(pk=pk)


def parent_for(project):
    record = ownership(project.anchor)
    if not record:
        return None
    lock_properties([record.property_id])
    parent = Property.objects.get(pk=record.property_id)
    if parent.state != "live" or not parent.owner_id or record.owner_id != parent.owner_id:
        raise ValidationError("The parent property needs staff repair.")
    if AttachmentAgreement.objects.filter(child=parent).exists() or ownership(parent.anchor):
        raise ValidationError("Nested apartments are not supported; choose a top-level parent.")
    return parent


def default_route(parent, anchor):
    """Use the parent's generated outward tree; callers can instead name a route."""
    from .services import _exit_data

    entry_id = _exit_data(parent.entrance)["target"] if parent.entrance else None
    records = {
        row.room_id: row
        for row in parent.promotion.project.rooms.filter(
            object_id__in=parent.rooms.values_list("object_id", flat=True)
        )
    }
    current = records.get(anchor.pk)
    by_id = {row.pk: row for row in records.values()}
    route = []
    while current:
        if current.room_id in route:
            break
        route.append(current.room_id)
        if current.room_id == entry_id:
            return list(reversed(route))
        current = by_id.get(current.parent_id)
    raise ValidationError("No usable parent passage was found; name an explicit route.")


def require_route_selection(actor, room_ids):
    """A proposal cannot be used to discover a restricted parent's geometry."""
    for room in ObjectDB.objects.filter(pk__in=room_ids):
        if (
            getattr(actor, "db_location_id", None) != room.pk
            and not can_enter(actor, room)
            and managed_access(room, actor, scope="maps") is not True
        ):
            raise PermissionDenied(
                "Ask the parent owner for entry or preview rights to the proposed passage before requesting attachment consent."
            )


def route_snapshot(parent, room_ids, anchor_id):
    from .services import _exit_data

    if (
        not isinstance(room_ids, list)
        or not room_ids
        or any(type(pk) is not int for pk in room_ids)
        or len(room_ids) != len(set(room_ids))
        or room_ids[-1] != anchor_id
    ):
        raise ValidationError("Passage must be a non-cyclic room route ending at the attachment.")
    entry = parent.rooms.filter(room__isnull=False, room_id=room_ids[0]).first()
    entrance = parent.entrance
    departure = parent.departure
    entrance_data = _exit_data(entrance) if entrance else {}
    departure_data = _exit_data(departure) if departure else {}
    if (
        not entry
        or not entrance
        or not departure
        or not parent.anchor_id
        or entrance_data["source"] != parent.anchor_id
        or entrance_data["target"] != room_ids[0]
        or departure_data["source"] != room_ids[0]
        or departure_data["target"] != parent.anchor_id
    ):
        raise ValidationError("Passage must start at the parent's usable entrance and departure.")
    if parent.rooms.filter(room_id__in=room_ids, owner_id=parent.owner_id).count() != len(room_ids):
        raise ValidationError(
            "The whole passage must lie in one parent property; cross-property routes are unsupported."
        )
    edges = []
    for source, target in pairwise(room_ids):
        for left, right in ((source, target), (target, source)):
            exits = ObjectDB.objects.filter(db_location_id=left, db_destination_id=right).order_by(
                "pk"
            )
            exit = exits.first()
            if not exit:
                raise ValidationError(
                    "Every passage segment needs a usable door in both directions."
                )
            data = _exit_data(exit)
            # Building controls these locks. Unknown custom locks cannot promise U7.
            if not _passage_lock(data["locks"]):
                raise ValidationError(
                    "Passage doors must use Building entry or unrestricted traversal locks."
                )
            edges.append(data)
    for data in (entrance_data, departure_data):
        if not _passage_lock(data["locks"]):
            raise ValidationError(
                "The parent's entrance/departure is not usable for agreed passage."
            )
    return {
        "parent": parent.pk,
        "anchor": anchor_id,
        "rooms": room_ids,
        "edges": edges,
        "entrance": entrance_data,
        "departure": departure_data,
    }


def _passage_lock(storage):
    return next(
        (
            part.strip().casefold()
            for part in storage.split(";")
            if part.strip().casefold().startswith("traverse:")
        ),
        "",
    ) in {"traverse:building_entry()", "traverse:all()"}


def attachment_snapshot(project):
    parent = parent_for(project)
    if not parent:
        if project.passage:
            raise ValidationError("A passage route requires a parent property.")
        return None
    return {
        "parent": parent.pk,
        "parent_owner": parent.owner_id,
        "route": route_snapshot(parent, project.passage, project.anchor_id),
    }


def validate_consent(project, candidate):
    from .services import fingerprint

    attachment = candidate.get("attachment")
    if not attachment:
        return None
    # Content reuse acknowledgement is the applicant's separate submission action.
    content = {
        key: value for key, value in candidate.items() if key not in {"acknowledgement", "consent"}
    }
    consent = (
        AttachmentConsent.objects.select_for_update()
        .filter(
            project=project,
            parent_id=attachment["parent"],
            owner_id=attachment["parent_owner"],
            owner_object_id=attachment["parent_owner"],
            applicant_object_id=project.owner_id,
            fingerprint=fingerprint(content),
            state="granted",
        )
        .order_by("-pk")
        .first()
    )
    if not consent:
        raise ValidationError(
            "The current parent owner must grant consent to this exact candidate and passage before submission or approval."
        )
    return consent


@atomic_objects
def request_consent(actor, project, *, expected_version):
    from . import services

    project = services._project(project, actor, editable=True, expected_version=expected_version)
    candidate = services.snapshot(project)
    attachment = candidate.get("attachment")
    if not attachment:
        raise ValidationError("This attachment has no other property boundary requiring consent.")
    parent = Property.objects.get(pk=attachment["parent"])
    digest = services.fingerprint(candidate)
    previous = project.consents.filter(
        fingerprint=digest, state__in=["requested", "granted"]
    ).first()
    if previous:
        return previous
    require_route_selection(actor, attachment["route"]["rooms"])
    consent = AttachmentConsent.objects.create(
        project=project,
        parent=parent,
        owner=parent.owner,
        owner_name=parent.owner_name,
        owner_object_id=parent.owner_id,
        applicant_object_id=actor.pk,
        candidate=candidate,
        fingerprint=digest,
        wording=WORDING,
        wording_version=WORDING_VERSION,
        state="granted" if actor.pk == parent.owner_id else "requested",
        answered_at=timezone.now() if actor.pk == parent.owner_id else None,
    )
    services.audit(
        actor,
        "consent_requested",
        project=project,
        consent=consent.pk,
        parent=parent.pk,
        self_owned=actor.pk == parent.owner_id,
    )
    return consent


def visible_consents(actor):
    require_revealed(actor)
    rows = AttachmentConsent.objects.select_related("project", "parent")
    return rows if is_staff(actor) else rows.filter(Q(project__owner=actor) | Q(owner=actor))


@atomic_objects
def answer_consent(actor, consent, *, action, acknowledgement=""):
    from . import services

    begin_write()
    require_revealed(actor)
    BuildProject.objects.filter(pk=consent.project_id).update(version=F("version"))
    project = BuildProject.objects.select_for_update().get(pk=consent.project_id)
    consent = AttachmentConsent.objects.select_for_update().get(pk=consent.pk)
    lock_properties([consent.parent_id])
    parent = Property.objects.get(pk=consent.parent_id)
    if consent.owner_id != actor.pk or parent.owner_id != actor.pk:
        raise PermissionDenied("Only the recorded, current parent owner may answer this consent.")
    if action == "revoke":
        if consent.state != "granted" or project.state not in {"draft", "submitted"}:
            raise ValidationError("Only unconsumed granted consent may be revoked.")
        consent.state = "revoked"
    elif action in {"grant", "decline"}:
        if consent.state != "requested" or project.state != "draft":
            raise ValidationError("This consent request is no longer pending.")
        if services.fingerprint(services.snapshot(project)) != consent.fingerprint:
            raise ValidationError("The candidate changed; ask for a new consent request.")
        if action == "grant" and acknowledgement != consent.wording:
            raise ValidationError("Read and explicitly acknowledge the passage agreement wording.")
        consent.state = "granted" if action == "grant" else "declined"
    else:
        raise ValidationError("Choose grant, decline or revoke.")
    consent.answered_at = timezone.now()
    consent.save(update_fields=["state", "answered_at"])
    services.audit(actor, "consent_" + consent.state, project=project, consent=consent.pk)
    return consent


def consume(submission, property):
    consent_id = submission.snapshot.get("consent")
    if not consent_id:
        return
    consent = AttachmentConsent.objects.select_for_update().get(pk=consent_id)
    if consent.state != "granted":
        raise ValidationError("Attachment consent was revoked or invalidated.")
    AttachmentAgreement.objects.create(
        child=property,
        parent=consent.parent,
        consent=consent,
        route=consent.candidate["attachment"]["route"],
        parent_owner_id_snapshot=consent.owner_object_id,
        child_owner_id_snapshot=property.owner_id,
    )
    consent.state = "consumed"
    consent.save(update_fields=["state"])


def route_valid(agreement, *, require_child_live=True):
    try:
        if agreement.parent.state != "live" or (
            require_child_live
            and (
                agreement.child.state != "live"
                or not agreement.child.owner_id
                or not agreement.child.entrance_id
                or not agreement.child.departure_id
            )
        ):
            return False
        return (
            route_snapshot(agreement.parent, agreement.route["rooms"], agreement.child.anchor_id)
            == agreement.route
        )
    except (ValidationError, ObjectDB.DoesNotExist):
        return False


def passage_allows(room, actor):
    """Physical entry only: no map, remote discovery, install or edit rights."""
    from .access import _granted

    if not actor:
        return False
    record = ownership(room)
    if not record:
        return False
    for agreement in AttachmentAgreement.objects.filter(
        parent_id=record.property_id
    ).select_related("parent", "child"):
        if room.pk not in agreement.route["rooms"] or not route_valid(agreement):
            continue
        child_entry = agreement.child.rooms.filter(
            room_id=agreement.child.entrance.db_destination_id
        ).first()
        if child_entry and (
            actor.pk == agreement.child.owner_id or _granted(child_entry, actor, "entry")
        ):
            return True
    return False


def departure_allows(exit):
    """Anyone already on an agreed route can leave, including after revocation."""
    # Every traversal asks this. Agreed routes lie wholly inside their parent, so
    # only that parent's agreements apply, and only a matching exit is revalidated.
    record = ownership(exit.location) if exit.db_location_id else None
    if not record:
        return False
    for agreement in AttachmentAgreement.objects.select_related("parent", "child").filter(
        parent_id=record.property_id, parent__state="live"
    ):
        rooms = agreement.route["rooms"]
        reverse_pairs = {(target, source) for source, target in pairwise(rooms)}
        if (
            exit.pk == agreement.route["departure"]["id"]
            or (exit.db_location_id, exit.db_destination_id) in reverse_pairs
        ) and route_valid(agreement, require_child_live=False):
            return True
    return False


def protected_exit(exit):
    for agreement in AttachmentAgreement.objects.all():
        route = agreement.route
        if exit.pk in {
            route["entrance"]["id"],
            route["departure"]["id"],
            *(edge["id"] for edge in route["edges"]),
        }:
            return True
        if exit.pk in {agreement.child.entrance_id, agreement.child.departure_id}:
            return True
    return False


@atomic_objects
def propose_passage(actor, agreement, room_ids, *, reason):
    from .services import _text, audit

    begin_write()
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only staff can propose replacement passage.")
    lock_properties([agreement.parent_id, agreement.child_id])
    agreement = AttachmentAgreement.objects.select_related("parent", "child").get(pk=agreement.pk)
    route = route_snapshot(agreement.parent, room_ids, agreement.child.anchor_id)
    change = PassageChange.objects.create(
        agreement=agreement,
        route=route,
        previous_route=agreement.route,
        parent_owner=agreement.parent.owner,
        child_owner=agreement.child.owner,
        wording=WORDING,
        reason=_text(reason, 10000),
    )
    audit(actor, "passage_proposed", property=agreement.child, change=change.pk)
    return change


@atomic_objects
def accept_passage(actor, change, *, acknowledgement):
    from .services import audit

    begin_write()
    require_revealed(actor)
    lock_properties([change.agreement.parent_id, change.agreement.child_id])
    change = (
        PassageChange.objects.select_for_update()
        .select_related("agreement__parent", "agreement__child")
        .get(pk=change.pk)
    )
    _current_change(change)
    if actor.pk not in {change.parent_owner_id, change.child_owner_id}:
        raise PermissionDenied(
            "Only an affected property owner may acknowledge replacement passage."
        )
    if acknowledgement != change.wording:
        raise ValidationError("Acknowledge the exact passage wording.")
    if actor.pk == change.parent_owner_id:
        change.parent_accepted = True
    if actor.pk == change.child_owner_id:
        change.child_accepted = True
    change.save(update_fields=["parent_accepted", "child_accepted"])
    audit(actor, "passage_accepted", property=change.agreement.child, change=change.pk)
    return change


def _current_change(change):
    agreement = change.agreement
    if (
        change.state != "pending"
        or agreement.route != change.previous_route
        or agreement.parent.owner_id != change.parent_owner_id
        or agreement.child.owner_id != change.child_owner_id
        or not change.parent_owner_id
        or not change.child_owner_id
    ):
        raise ValidationError("The route or owners changed; propose replacement passage again.")
    if (
        route_snapshot(agreement.parent, change.route["rooms"], agreement.child.anchor_id)
        != change.route
    ):
        raise ValidationError("The proposed passage changed; obtain fresh agreement.")


@atomic_objects
def apply_passage(actor, change):
    from .services import _changed

    begin_write()
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only staff can establish replacement passage.")
    lock_properties([change.agreement.parent_id, change.agreement.child_id])
    change = (
        PassageChange.objects.select_for_update()
        .select_related("agreement__parent", "agreement__child")
        .get(pk=change.pk)
    )
    _current_change(change)
    if not change.parent_accepted or not change.child_accepted:
        raise ValidationError("Both affected owners must agree to replacement passage.")
    agreement = change.agreement
    agreement.route = change.route
    agreement.parent_owner_id_snapshot = change.parent_owner_id
    agreement.child_owner_id_snapshot = change.child_owner_id
    agreement.save(update_fields=["route", "parent_owner_id_snapshot", "child_owner_id_snapshot"])
    change.state = "applied"
    change.save(update_fields=["state"])
    _changed(agreement.child, actor, "passage_changed", change=change.pk, reason=change.reason)
    return agreement
