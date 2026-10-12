"""Authenticated pages; selected characters and services own every write."""

from contextlib import suppress

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods
from evennia.objects.models import ObjectDB

from evennia_links.characters import web_character

from . import attachments, collaboration, frontier_lifecycle, lifecycle, services
from .access import is_staff, require_revealed
from .models import (
    AttachmentAgreement,
    BuildProject,
    BuildSubmission,
    GuestInvitation,
    PassageChange,
    ProjectContributor,
    Property,
)
from .policy import set_policy
from .visibility import room_visibility


class ProjectForm(forms.Form):
    name = forms.CharField(max_length=255)
    kind = forms.ChoiceField(
        choices=[("interior", "Interior"), ("frontier", "Public frontier / settlement")],
        required=False,
    )
    purpose = forms.ChoiceField(
        choices=[
            ("home", "Home"),
            ("public", "Public frontier"),
            ("shop", "Shop proposal (selling requires a separate shop integration)"),
        ]
    )

    def clean_kind(self):
        return self.cleaned_data["kind"] or "interior"


class ActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            (key, label)
            for key, label in (
                ("name", "Rename project"),
                ("purpose", "Change purpose"),
                ("room_name", "Rename room"),
                ("description", "Describe room"),
                ("dig", "Add room"),
                ("door", "Add internal door"),
                ("attach", "Choose attachment"),
                ("submit", "Submit exact version"),
                ("withdraw", "Withdraw submission"),
                ("review", "Staff review"),
                ("lock", "Lock home"),
                ("unlock", "Unlock home"),
                ("resident", "Add/update resident"),
                ("remove_resident", "Remove resident"),
                ("invite", "Invite guest"),
                ("uninvite", "Revoke invitation"),
                ("override", "Set room access override"),
                ("reset_override", "Reset room access"),
                ("transfer", "Staff transfer"),
                ("discard", "Confirm discard"),
                ("environment", "Request environment changes"),
                ("approve_environment", "Approve requested environment (staff)"),
                ("approve_geometry", "Certify manually reviewed frontier geometry (staff)"),
                ("policy", "Set room building policy (staff)"),
                ("region_policy", "Set region building policy (staff)"),
                ("consent_request", "Request attachment consent"),
                ("archive", "Archive property (staff)"),
                ("restore", "Restore property (staff)"),
                ("passage", "Propose replacement passage (staff)"),
            )
        ]
    )
    version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    room = forms.IntegerField(
        min_value=1, required=False, label="Draft room number (or property room)"
    )
    target = forms.IntegerField(
        min_value=1, required=False, label="Target room / attachment / character"
    )
    value = forms.CharField(
        required=False,
        max_length=50000,
        widget=forms.Textarea,
        label="Name, description, purpose, review outcome or allowed character numbers",
    )
    door = forms.CharField(required=False, max_length=100, initial="inside")
    back = forms.CharField(required=False, max_length=100, initial="out")
    floor = forms.IntegerField(required=False, initial=0)
    x = forms.IntegerField(required=False, initial=0)
    y = forms.IntegerField(required=False, initial=0)
    reason = forms.CharField(required=False, max_length=10000, widget=forms.Textarea)
    acknowledgement = forms.CharField(
        required=False, widget=forms.Textarea, label="Copy the displayed acknowledgement to submit"
    )
    can_install = forms.BooleanField(
        required=False, label="Explicitly allow this resident to install"
    )
    entry = forms.BooleanField(required=False, initial=True, label="Guest may enter locked rooms")
    maps = forms.BooleanField(required=False, initial=True, label="Guest may view interior maps")
    retain_grants = forms.BooleanField(required=False, label="Retain grants during staff transfer")
    expected_owner = forms.IntegerField(min_value=1, required=False)
    confirmation = forms.CharField(required=False, widget=forms.HiddenInput)
    passage = forms.CharField(
        required=False,
        label="Passage room numbers, from parent entrance to apartment attachment, separated by commas",
    )
    include_children = forms.BooleanField(
        required=False, label="Archive affected apartments together with this parent"
    )

    def __init__(self, data=None, *, actions, selected=None, rooms=(), **kwargs):
        super().__init__(data, **kwargs)
        self.action_choices = [
            (key, label) for key, label in self.fields["action"].choices if key in actions
        ]
        action = (data.get("action") if data is not None else selected) or self.action_choices[0][0]
        self.selected_action = action
        self.fields["action"].choices = self.action_choices
        self.fields["action"].initial = action
        self.fields["action"].widget = forms.HiddenInput()
        fields = {
            "name": ("version", "value"),
            "purpose": ("version", "value"),
            "room_name": ("version", "room", "value"),
            "description": ("version", "room", "value"),
            "dig": ("version", "room", "value", "door", "back", "floor", "x", "y"),
            "door": ("version", "room", "target", "value"),
            "attach": ("version", "target", "value", "passage"),
            "consent_request": ("version",),
            "archive": ("reason", "include_children"),
            "restore": ("reason",),
            "passage": ("passage", "reason"),
            "submit": ("version", "acknowledgement"),
            "discard": ("version", "confirmation"),
            "environment": ("version", "value"),
            "approve_environment": ("version", "reason"),
            "approve_geometry": ("version", "reason"),
            "withdraw": ("version", "reason"),
            "review": ("version", "value", "reason"),
            "lock": (),
            "unlock": (),
            "resident": ("target", "can_install"),
            "remove_resident": ("target",),
            "invite": ("target", "entry", "maps"),
            "uninvite": ("target",),
            "override": ("room", "value"),
            "reset_override": ("room",),
            "transfer": ("target", "expected_owner", "reason", "retain_grants"),
            "policy": ("target", "value"),
            "region_policy": ("target", "value"),
        }.get(action, ())
        for key in list(self.fields):
            if key != "action" and key not in fields:
                del self.fields[key]
        if "version" in self.fields and "version" not in self.initial:
            del self.fields["version"]
        for key, field in self.fields.items():
            if key not in {
                "reason",
                "can_install",
                "retain_grants",
                "entry",
                "maps",
                "value",
                "passage",
                "include_children",
            }:
                field.required = True
        if "value" in self.fields:
            self.fields["value"].label = {
                "description": "Room description",
                "environment": 'Environment request as JSON, for example {"terrain": ["urban"]}; {} resets inheritance',
                "review": "Review outcome",
                "purpose": "Purpose",
                "override": "Allowed character numbers, separated by commas (empty: owner only)",
                "policy": "Room policy",
                "region_policy": "Region policy",
                "attach": "Entrance name",
                "door": "Door name",
            }.get(action, "Name")
            if action in {"purpose", "review", "policy", "region_policy"}:
                choices = {
                    "purpose": ("home", "shop"),
                    "review": ("approved", "changes_requested", "declined"),
                }.get(action, ("open", "residential", "commercial", "closed", "reset"))
                self.fields["value"] = forms.ChoiceField(
                    label=self.fields["value"].label,
                    choices=[(key, key.replace("_", " ").capitalize()) for key in choices],
                )
        if "room" in self.fields:
            self.fields["room"].widget = forms.Select(choices=rooms)
        if "target" in self.fields:
            self.fields["target"].label = (
                "Region number"
                if action == "region_policy"
                else "Attachment room number"
                if action == "attach"
                else "Target draft room number"
                if action == "door"
                else "Room number"
                if action == "policy"
                else "Character number"
            )


def preview_links(rooms, actor):
    if not apps.is_installed("evennia_maps"):
        return []
    from evennia_maps.models import RoomTile
    from evennia_maps.permissions import is_plane_visible

    links = []
    planes = {}
    for tile in RoomTile.objects.filter(room__in=rooms).select_related("plane"):
        planes[tile.plane_id] = tile.plane
    for plane in planes.values():
        if is_plane_visible(plane, viewer=actor, staff=is_staff(actor)):
            with suppress(NoReverseMatch):
                links.append((plane.name, reverse("evennia_maps:plane-detail", args=[plane.pk])))
    return links


def actor_for(request):
    actor = web_character(request.user)
    require_revealed(actor)
    return actor


def project_for(actor, pk):
    project = get_object_or_404(BuildProject, pk=pk)
    if not collaboration.can_inspect(actor, project):
        raise Http404
    return project


def property_rooms(property, actor):
    return [
        record.room
        for record in property.rooms.select_related("room")
        if record.room and room_visibility(record.room, actor)
    ]


def _error(form, exc):
    form.add_error(
        None,
        "; ".join(exc.messages)
        if isinstance(exc, ValidationError)
        else str(exc) or "Check the selected action and its required fields.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def index(request):
    actor = actor_for(request)
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            project = services.new_project(actor, **form.cleaned_data)
            return redirect("evennia_building:project", pk=project.pk)
        except (ValidationError, PermissionDenied) as exc:
            _error(form, exc)
    projects = collaboration.visible_projects(actor)
    properties = [
        property
        for property in (
            Property.objects.all() if is_staff(actor) else Property.objects.filter(state="live")
        )
        if is_staff(actor) or property_rooms(property, actor)
    ]
    return render(
        request,
        "evennia_building/index.html",
        {
            "projects": projects,
            "pending_reviews": BuildSubmission.objects.filter(
                project__state="submitted", review__isnull=True
            )
            if is_staff(actor)
            else (),
            "properties": properties,
            "invitations": GuestInvitation.objects.filter(character=actor, state="pending"),
            "form": form,
            "consents": attachments.visible_consents(actor),
            "passage_changes": PassageChange.objects.filter(state="pending")
            if is_staff(actor)
            else PassageChange.objects.filter(
                Q(parent_owner=actor) | Q(child_owner=actor), state="pending"
            ),
            "quiet_flags": lifecycle.quiet_list(actor) if is_staff(actor) else (),
            "steward_flags": frontier_lifecycle.quiet_list(actor) if is_staff(actor) else (),
            "collaboration_invitations": ProjectContributor.objects.filter(
                character=actor, state="invited"
            ).select_related("project"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_detail(request, pk):
    actor = actor_for(request)
    project = project_for(actor, pk)
    rooms = list(project.rooms.select_related("room"))
    actions = (
        {
            "name",
            "purpose",
            "room_name",
            "description",
            "dig",
            "door",
            "attach",
            "submit",
            "discard",
            "environment",
            "consent_request",
        }
        if project.state == "draft" and actor.pk == project.owner_id
        else {"submit"}
    )
    if actor.pk != project.owner_id:
        actions = (
            {"room_name", "description", "dig", "door"}
            if project.state == "draft" and collaboration.can_author(actor, project)
            else set()
        )
    form = (
        ActionForm(
            request.POST if request.method == "POST" else None,
            actions=actions,
            selected=request.GET.get("action"),
            initial={"version": project.version},
            rooms=[(row.pk, row.room.key if row.room else "Missing room") for row in rooms],
        )
        if actions
        else None
    )
    if request.method == "POST" and form is None:
        raise PermissionDenied("This candidate is available for inspection and agreement only.")
    if request.method == "POST" and form.is_valid():
        try:
            values = form.cleaned_data
            action = values["action"]
            if values["version"] != project.version:
                raise ValidationError("This project has changed; reload it first.")
            if action in {"name", "purpose", "room_name", "description"}:
                room = (
                    project.rooms.get(pk=values["room"])
                    if action in {"room_name", "description"}
                    else None
                )
                field = "name" if action == "room_name" else action
                services.edit_project(
                    actor,
                    project,
                    room=room,
                    expected_version=values["version"],
                    **{field: values["value"]},
                )
            elif action == "dig":
                services.dig(
                    actor,
                    project,
                    project.rooms.get(pk=values["room"]),
                    values["value"],
                    door=values["door"],
                    back=values["back"],
                    floor=values["floor"],
                    x=values["x"],
                    y=values["y"],
                    expected_version=values["version"],
                )
            elif action == "door":
                services.add_door(
                    actor,
                    project,
                    project.rooms.get(pk=values["room"]),
                    project.rooms.get(pk=values["target"]),
                    values["value"],
                    expected_version=values["version"],
                )
            elif action == "attach":
                services.attach(
                    actor,
                    project,
                    ObjectDB.objects.get(pk=values["target"]),
                    values["value"],
                    expected_version=values["version"],
                    passage=[int(pk.strip()) for pk in values["passage"].split(",")]
                    if values.get("passage")
                    else None,
                )
            elif action == "consent_request":
                consent = attachments.request_consent(
                    actor, project, expected_version=values["version"]
                )
                return redirect("evennia_building:consent", pk=consent.pk)
            elif action == "submit":
                services.submit(
                    actor,
                    project,
                    expected_version=values["version"],
                    acknowledgement=values["acknowledgement"],
                )
            elif action == "environment":
                import json

                services.request_environment(
                    actor, project, json.loads(values["value"]), expected_version=values["version"]
                )
            elif action == "discard":
                services.discard(actor, project, values["confirmation"])
            else:
                raise ValidationError("Use the submission or property page for this action.")
            return redirect("evennia_building:project", pk=pk)
        except (
            ValidationError,
            PermissionDenied,
            ObjectDoesNotExist,
            ValueError,
            TypeError,
        ) as exc:
            _error(form, exc)
    confirmation = (
        services.discard_token(actor, project)
        if project.state == "draft" and actor.pk == project.owner_id
        else ""
    )
    if form and "confirmation" in form.fields:
        form.fields["confirmation"].initial = confirmation
    return render(
        request,
        "evennia_building/project.html",
        {
            "project": project,
            "rooms": rooms,
            "previews": preview_links([row.room for row in rooms if row.room], actor),
            "submissions": project.submissions.all(),
            "audit": project.audit.all(),
            "form": form,
            "acknowledgement": getattr(
                settings,
                "BUILDING_REUSE_ACKNOWLEDGEMENT",
                "I acknowledge that this submitted content may be reused by this game.",
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def submission_detail(request, pk):
    actor = actor_for(request)
    submission = get_object_or_404(BuildSubmission, pk=pk)
    project_for(actor, submission.project_id)
    form = ActionForm(
        request.POST if request.method == "POST" else None,
        actions={"withdraw", "review", "approve_environment", "approve_geometry"}
        if is_staff(actor)
        else {"withdraw"},
        selected=request.GET.get("action"),
        initial={"version": submission.revision},
    )
    if request.method == "POST" and form.is_valid():
        try:
            values = form.cleaned_data
            if values["action"] == "withdraw":
                services.withdraw(
                    actor, submission, expected_revision=values["version"], reason=values["reason"]
                )
            elif values["action"] == "review":
                services.review(
                    actor,
                    submission,
                    expected_revision=values["version"],
                    outcome=values["value"],
                    reason=values["reason"],
                )
            elif values["action"] == "approve_environment":
                services.approve_environment(
                    actor, submission, expected_revision=values["version"], reason=values["reason"]
                )
            elif values["action"] == "approve_geometry":
                from .frontier import approve_geometry

                approve_geometry(
                    actor, submission, expected_revision=values["version"], reason=values["reason"]
                )
            else:
                raise ValidationError("Choose withdrawal or staff review.")
            return redirect("evennia_building:submission", pk=pk)
        except (ValidationError, PermissionDenied) as exc:
            _error(form, exc)
    return render(
        request,
        "evennia_building/submission.html",
        {"submission": submission, "snapshot": json_snapshot(submission), "form": form},
    )


def json_snapshot(submission):
    import json

    return json.dumps(submission.snapshot, indent=2, ensure_ascii=False)


@login_required
@require_http_methods(["GET", "POST"])
def property_detail(request, pk):
    actor = actor_for(request)
    property = get_object_or_404(Property, pk=pk)
    if property.state != "live" and not is_staff(actor):
        raise Http404
    rooms = property_rooms(property, actor)
    if not rooms and not is_staff(actor):
        raise Http404
    manager = actor.pk == property.owner_id or is_staff(actor)
    actions = {
        "lock",
        "unlock",
        "resident",
        "remove_resident",
        "invite",
        "uninvite",
        "override",
        "reset_override",
        "room_name",
        "description",
    }
    if is_staff(actor):
        actions |= {"transfer", "policy", "region_policy", "archive", "restore"}
        if AttachmentAgreement.objects.filter(child=property).exists():
            actions.add("passage")
    form = ActionForm(
        request.POST if request.method == "POST" else None,
        actions=actions,
        selected=request.GET.get("action"),
        rooms=[(room.pk, room.key) for room in rooms],
    )
    if request.method == "POST" and form.is_valid():
        try:
            values = form.cleaned_data
            action = values["action"]
            target = (
                ObjectDB.objects.get(pk=values["target"])
                if values.get("target") and action != "region_policy"
                else None
            )
            if action in {"lock", "unlock"}:
                services.set_locked(actor, property, action == "lock")
            elif action in {"resident", "remove_resident"}:
                services.set_resident(
                    actor,
                    property,
                    target,
                    remove=action == "remove_resident",
                    can_install=values.get("can_install", False),
                )
            elif action in {"invite", "uninvite"}:
                services.invite(
                    actor,
                    property,
                    target,
                    revoke=action == "uninvite",
                    entry=values.get("entry", True),
                    maps=values.get("maps", True),
                )
            elif action in {"override", "reset_override"}:
                room = property.rooms.get(room_id=values["room"]).room
                allowed = (
                    None
                    if action == "reset_override"
                    else [
                        int(value.strip()) for value in values["value"].split(",") if value.strip()
                    ]
                )
                services.set_override(actor, room, allowed)
            elif action in {"room_name", "description"}:
                room = property.rooms.get(room_id=values["room"]).room
                services.edit_property_room(
                    actor,
                    room,
                    **{"name" if action == "room_name" else "description": values["value"]},
                )
            elif action == "transfer":
                services.transfer(
                    actor,
                    property,
                    target,
                    expected_owner=values["expected_owner"],
                    reason=values["reason"],
                    retain_grants=values["retain_grants"],
                )
            elif action in {"policy", "region_policy"}:
                set_policy(
                    actor,
                    values["target"] if action == "region_policy" else target,
                    values["value"],
                    region=action == "region_policy",
                )
            elif action == "archive":
                lifecycle.archive(
                    actor,
                    property,
                    reason=values["reason"],
                    include_children=values["include_children"],
                )
            elif action == "restore":
                lifecycle.restore(actor, property, reason=values["reason"])
            elif action == "passage":
                change = attachments.propose_passage(
                    actor,
                    property.attachment,
                    [int(pk.strip()) for pk in values["passage"].split(",")],
                    reason=values["reason"],
                )
                return redirect("evennia_building:passage", pk=change.pk)
            else:
                raise ValidationError("Choose a property action.")
            return redirect("evennia_building:property", pk=pk)
        except (
            ValidationError,
            PermissionDenied,
            ObjectDoesNotExist,
            ValueError,
            TypeError,
        ) as exc:
            _error(form, exc)
    return render(
        request,
        "evennia_building/property.html",
        {
            "property": property,
            "rooms": rooms,
            "manager": manager,
            "form": form,
            "previews": preview_links(rooms, actor),
            "residents": property.residents.select_related("character") if manager else (),
            "invitations": property.invitations.select_related("character") if manager else (),
            "audit": property.audit.all() if manager else (),
        },
    )


@login_required
@require_http_methods(["POST"])
def invitation_answer(request, pk):
    actor = actor_for(request)
    invitation = get_object_or_404(GuestInvitation, pk=pk, character=actor)
    answer = request.POST.get("answer")
    try:
        if answer not in {"accept", "decline"}:
            raise ValidationError("Choose accept or decline.")
        services.answer_invitation(actor, invitation, accept=answer == "accept")
    except ValidationError as exc:
        return render(
            request,
            "evennia_building/invitation_error.html",
            {"error": "; ".join(exc.messages)},
            status=400,
        )
    return redirect("evennia_building:index")


class ConsentAnswerForm(forms.Form):
    action = forms.ChoiceField(
        choices=[("grant", "Grant"), ("decline", "Decline"), ("revoke", "Revoke before promotion")]
    )
    acknowledgement = forms.BooleanField(
        required=False, label="I have read and agree to the exact passage wording shown above."
    )


@login_required
@require_http_methods(["GET", "POST"])
def consent_detail(request, pk):
    import json

    actor = actor_for(request)
    consent = get_object_or_404(attachments.visible_consents(actor), pk=pk)
    form = ConsentAnswerForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            attachments.answer_consent(
                actor,
                consent,
                action=form.cleaned_data["action"],
                acknowledgement=consent.wording if form.cleaned_data["acknowledgement"] else "",
            )
            return redirect("evennia_building:consent", pk=pk)
        except (ValidationError, PermissionDenied) as exc:
            _error(form, exc)
    return render(
        request,
        "evennia_building/consent.html",
        {
            "consent": consent,
            "snapshot": json.dumps(consent.candidate, indent=2),
            "form": form,
            "may_answer": actor.pk == consent.owner_id,
        },
    )


class PassageAnswerForm(forms.Form):
    action = forms.ChoiceField(
        choices=[("accept", "Acknowledge replacement passage"), ("apply", "Apply (staff)")]
    )
    acknowledgement = forms.BooleanField(
        required=False, label="I agree to the exact replacement route and passage wording above."
    )


@login_required
@require_http_methods(["GET", "POST"])
def passage_detail(request, pk):
    actor = actor_for(request)
    change = get_object_or_404(PassageChange, pk=pk)
    if not is_staff(actor) and actor.pk not in {change.parent_owner_id, change.child_owner_id}:
        raise Http404
    form = PassageAnswerForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            if form.cleaned_data["action"] == "apply":
                attachments.apply_passage(actor, change)
            else:
                attachments.accept_passage(
                    actor,
                    change,
                    acknowledgement=change.wording if form.cleaned_data["acknowledgement"] else "",
                )
            return redirect("evennia_building:passage", pk=pk)
        except (ValidationError, PermissionDenied) as exc:
            _error(form, exc)
    return render(request, "evennia_building/passage.html", {"change": change, "form": form})
