"""Project-scoped authorship, retained contribution history and revision agreement."""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from evennia_links.transactions import atomic_objects

from .access import is_staff, require_revealed
from .attachments import begin_write
from .models import BuildProject, ProjectAgreement, ProjectContributor


def can_author(actor, project):
    return bool(
        actor
        and (
            actor.pk == project.owner_id
            or project.contributors.filter(character=actor, state="accepted").exists()
        )
    )


def can_inspect(actor, project):
    return bool(
        actor
        and (
            is_staff(actor)
            or can_author(actor, project)
            or project.proposed_owner_id == actor.pk
            or project.parts.filter(owner=actor).exists()
            or project.contributors.filter(character=actor, contributed=True).exists()
        )
    )


def visible_projects(actor):
    if is_staff(actor):
        return BuildProject.objects.all()
    return BuildProject.objects.filter(
        Q(owner=actor)
        | Q(proposed_owner=actor)
        | Q(parts__owner=actor)
        | Q(contributors__character=actor, contributors__state="accepted")
        | Q(contributors__character=actor, contributors__contributed=True)
    ).distinct()


def note_contribution(actor, project):
    if actor.pk != project.owner_id:
        project.contributors.filter(character=actor, state="accepted").update(contributed=True)


@atomic_objects
def invite(actor, project, character, *, expected_version=None, remove=False):
    from .services import _character, _project, _touch, audit

    begin_write()
    project = _project(project, actor, editable=True, expected_version=expected_version)
    _character(character)
    if character.pk == project.owner_id:
        raise ValidationError("The lead already has project access.")
    row, _ = ProjectContributor.objects.get_or_create(
        project=project,
        character_object_id=character.pk,
        defaults={"character": character, "character_name": character.key},
    )
    row.state = "removed" if remove else "invited"
    row.save(update_fields=["state"])
    _touch(project)
    audit(
        actor,
        "collaborator_removed" if remove else "collaborator_invited",
        project=project,
        character=character.pk,
    )
    return row


@atomic_objects
def answer(actor, invitation, *, accept=True, leave=False):
    from .services import _touch, audit

    begin_write()
    require_revealed(actor)
    project = BuildProject.objects.select_for_update().get(pk=invitation.project_id)
    row = ProjectContributor.objects.select_for_update().get(pk=invitation.pk)
    if row.character_id != actor.pk:
        raise PermissionDenied("Only the named character can answer or leave.")
    if project.state != "draft" and not (leave and project.state == "promoted"):
        raise ValidationError("Withdraw before changing collaboration membership.")
    if type(accept) is not bool or type(leave) is not bool:
        raise ValidationError("Choose an explicit answer.")
    if leave:
        if row.state != "accepted":
            raise ValidationError("You are not an active collaborator.")
        row.state = "left"
    else:
        if row.state != "invited":
            raise ValidationError("This invitation is no longer pending.")
        row.state = "accepted" if accept else "declined"
    row.save(update_fields=["state"])
    if project.state == "draft":
        _touch(project)
    audit(actor, "collaborator_" + row.state, project=project, character=actor.pk)
    return row


def wording(role):
    if role == "contributor":
        return getattr(
            settings,
            "BUILDING_REUSE_ACKNOWLEDGEMENT",
            "I acknowledge that this submitted content may be reused by this game.",
        )
    if role == "ownership":
        return "I accept the interior ownership boundaries assigned to me in this exact candidate."
    raise ValidationError("Choose contributor or ownership agreement.")


def required(project):
    roles = {
        (pk, "contributor")
        for pk in project.contributors.filter(
            Q(state="accepted") | Q(contributed=True)
        ).values_list("character_object_id", flat=True)
    }
    roles |= {(pk, "ownership") for pk in project.parts.values_list("owner_id", flat=True)}
    if project.proposed_owner_id and project.proposed_owner_id != project.owner_id:
        roles.add((project.proposed_owner_id, "ownership"))
    return roles


def extend_snapshot(project, candidate):
    if project.contributors.exists() or project.proposed_owner_id or project.parts.exists():
        candidate["collaboration"] = list(
            project.contributors.order_by("character_object_id").values(
                "character_object_id", "state", "contributed"
            )
        )
        candidate["proposed_owner"] = project.proposed_owner_id or project.owner_id
        candidate["agreement_terms"] = {
            "reuse": wording("contributor"),
            "reuse_version": str(getattr(settings, "BUILDING_REUSE_VERSION", "1")),
            "ownership": wording("ownership"),
            "ownership_version": "1",
        }


@atomic_objects
def acknowledge(actor, project, *, role, expected_version, expected_fingerprint, acknowledgement):
    from .services import audit, fingerprint, snapshot

    begin_write()
    require_revealed(actor)
    project = BuildProject.objects.select_for_update().get(pk=project.pk)
    if project.state != "draft" or project.version != expected_version:
        raise ValidationError("Acknowledge the current editable candidate before submission.")
    if not can_inspect(actor, project) or (actor.pk, role) not in required(project):
        raise PermissionDenied("This candidate does not request that agreement from you.")
    candidate = snapshot(project)
    digest = fingerprint(candidate)
    if digest != expected_fingerprint or acknowledgement != wording(role):
        raise ValidationError("Inspect the exact candidate and copy its current agreement wording.")
    existing = project.agreements.filter(
        actor_object_id=actor.pk, role=role, fingerprint=digest, state="accepted"
    ).first()
    if existing:
        return existing
    receipt = ProjectAgreement.objects.create(
        project=project,
        actor=actor,
        actor_object_id=actor.pk,
        role=role,
        candidate=candidate,
        fingerprint=digest,
        wording=wording(role),
        wording_version=str(getattr(settings, "BUILDING_REUSE_VERSION", "1"))
        if role == "contributor"
        else "1",
    )
    audit(
        actor,
        "candidate_acknowledged",
        project=project,
        agreement=receipt.pk,
        role=role,
        fingerprint=digest,
    )
    return receipt


@atomic_objects
def revoke(actor, receipt):
    from .services import audit

    begin_write()
    require_revealed(actor)
    project = BuildProject.objects.select_for_update().get(pk=receipt.project_id)
    receipt = ProjectAgreement.objects.select_for_update().get(pk=receipt.pk)
    if receipt.actor_id != actor.pk:
        raise PermissionDenied("Only the granting character can revoke this agreement.")
    if project.state not in {"draft", "submitted"} or receipt.state != "accepted":
        raise ValidationError("This agreement can no longer be revoked.")
    receipt.state = "revoked"
    receipt.save(update_fields=["state"])
    audit(actor, "candidate_agreement_revoked", project=project, agreement=receipt.pk)
    return receipt


def validate(project, candidate):
    from .services import fingerprint

    digest = fingerprint(candidate)
    receipts = []
    for actor_id, role in sorted(required(project)):
        receipt = (
            project.agreements.filter(
                actor_object_id=actor_id, role=role, fingerprint=digest, state="accepted"
            )
            .order_by("pk")
            .first()
        )
        if (
            not receipt
            or receipt.actor_id != actor_id
            or receipt.candidate != candidate
            or receipt.wording != wording(role)
        ):
            raise ValidationError(
                f"Character #{actor_id} must acknowledge the exact candidate ({role})."
            )
        receipts.append(receipt.pk)
    return receipts
