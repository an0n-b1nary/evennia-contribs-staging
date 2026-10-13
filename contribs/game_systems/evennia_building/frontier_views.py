"""Selected-character controls for shared drafts and public frontier maintenance."""

from datetime import date

from django import forms
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from evennia.objects.models import ObjectDB

from . import collaboration, frontier, frontier_lifecycle, services
from .access import is_staff
from .models import Frontier, FrontierRoom, ProjectContributor, Property
from .views import _error, actor_for, project_for


class ProjectControlForm(forms.Form):
    action = forms.ChoiceField()
    version = forms.IntegerField(widget=forms.HiddenInput)
    fingerprint = forms.CharField(widget=forms.HiddenInput)
    character = forms.IntegerField(min_value=1, label="Character number")
    street = forms.ModelChoiceField(queryset=None, label="Frontier street")
    part = forms.ModelChoiceField(
        queryset=None, required=False, label="Interior boundary (blank for a standalone interior)"
    )
    name = forms.CharField(max_length=255, label="Interior name")
    entrance = forms.CharField(max_length=100, label="Entrance name")
    purpose = forms.ChoiceField(choices=[("home", "Home"), ("shop", "Shop")])
    direction = forms.CharField(max_length=100, label="Compass direction")
    target = forms.IntegerField(min_value=1, label="Existing public room number")
    acknowledgement = forms.CharField(
        widget=forms.Textarea, label="Copy the displayed agreement wording"
    )
    receipt = forms.ModelChoiceField(queryset=None, label="Your candidate agreement")

    actions = {  # noqa: RUF012
        "invite": ("Invite collaborator", ("version", "character")),
        "remove": ("Remove collaborator", ("version", "character")),
        "assign": ("Assign proposed interior owner", ("version", "part", "character")),
        "interior": (
            "Add an independently owned interior",
            ("version", "street", "name", "entrance", "purpose", "character"),
        ),
        "connect": (
            "Propose an additional grid connection",
            ("version", "street", "target", "direction"),
        ),
        "disconnect": (
            "Remove a proposed grid connection",
            ("version", "street", "target", "direction"),
        ),
        "ack_contributor": (
            "Acknowledge my contribution",
            ("version", "fingerprint", "acknowledgement"),
        ),
        "ack_ownership": (
            "Accept my proposed ownership",
            ("version", "fingerprint", "acknowledgement"),
        ),
        "revoke": ("Revoke my candidate agreement", ("receipt",)),
    }

    def __init__(self, data=None, *, project, actor, actions, selected=None, **kwargs):
        super().__init__(data, **kwargs)
        self.fields["street"].queryset = project.rooms.filter(part__isnull=True)
        self.fields["street"].label_from_instance = lambda row: (
            f"{row.room.key if row.room else 'Missing'} (room {row.pk})"
        )
        self.fields["part"].queryset = project.parts.all()
        self.fields["part"].label_from_instance = lambda row: row.name
        self.fields["receipt"].queryset = project.agreements.filter(actor=actor, state="accepted")
        self.fields["receipt"].label_from_instance = lambda row: (
            f"{row.role}, candidate {row.fingerprint[:12]}"
        )
        self.action_choices = [(key, self.actions[key][0]) for key in actions]
        selected = (data.get("action") if data is not None else selected) or actions[0]
        self.selected_action = selected
        self.fields["action"].choices = self.action_choices
        self.fields["action"].widget = forms.HiddenInput()
        self.fields["action"].initial = selected
        keep = self.actions.get(selected, ("", ()))[1]
        for name in list(self.fields):
            if name != "action" and name not in keep:
                del self.fields[name]


@login_required
@require_http_methods(["GET", "POST"])
def collaboration_detail(request, pk):
    actor = actor_for(request)
    project = project_for(actor, pk)
    actions = []
    if project.state == "draft":
        if actor.pk == project.owner_id:
            actions += ["invite", "remove", "assign"]
            if project.kind == "frontier":
                actions += ["interior", "connect", "disconnect"]
        actions += [
            "ack_" + role
            for actor_id, role in sorted(collaboration.required(project))
            if actor_id == actor.pk
        ]
    if (
        project.state in {"draft", "submitted"}
        and project.agreements.filter(actor=actor, state="accepted").exists()
    ):
        actions += ["revoke"]
    candidate, candidate_error = None, ""
    try:
        candidate = services.snapshot(project) if project.state in {"draft", "submitted"} else None
    except ValidationError as exc:
        candidate_error = "; ".join(exc.messages)
    digest = services.fingerprint(candidate) if candidate else ""
    form = (
        ProjectControlForm(
            request.POST if request.method == "POST" else None,
            project=project,
            actor=actor,
            actions=actions,
            selected=request.GET.get("action"),
            initial={"version": project.version, "fingerprint": digest},
        )
        if actions
        else None
    )
    if request.method == "POST":
        if form is None:
            raise PermissionDenied("No project-management or agreement action is available.")
        if form.is_valid():
            try:
                values = form.cleaned_data
                action = values["action"]
                if action in {"invite", "remove"}:
                    collaboration.invite(
                        actor,
                        project,
                        ObjectDB.objects.get(pk=values["character"]),
                        expected_version=values["version"],
                        remove=action == "remove",
                    )
                elif action == "assign":
                    frontier.assign_owner(
                        actor,
                        project,
                        ObjectDB.objects.get(pk=values["character"]),
                        part=values["part"],
                        expected_version=values["version"],
                    )
                elif action == "interior":
                    frontier.add_interior(
                        actor,
                        project,
                        values["street"],
                        values["name"],
                        owner=ObjectDB.objects.get(pk=values["character"]),
                        entrance_name=values["entrance"],
                        purpose=values["purpose"],
                        expected_version=values["version"],
                    )
                elif action in {"connect", "disconnect"}:
                    frontier.propose_connection(
                        actor,
                        project,
                        values["street"],
                        ObjectDB.objects.filter(pk=values["target"]).first()
                        if action == "disconnect"
                        else ObjectDB.objects.get(pk=values["target"]),
                        values["direction"],
                        expected_version=values["version"],
                        remove=action == "disconnect",
                    )
                elif action.startswith("ack_"):
                    collaboration.acknowledge(
                        actor,
                        project,
                        role=action.removeprefix("ack_"),
                        expected_version=values["version"],
                        expected_fingerprint=values["fingerprint"],
                        acknowledgement=values["acknowledgement"],
                    )
                elif action == "revoke":
                    collaboration.revoke(actor, values["receipt"])
                return redirect("evennia_building:collaboration", pk=project.pk)
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
        "evennia_building/collaboration.html",
        {
            "project": project,
            "form": form,
            "candidate": candidate,
            "candidate_error": candidate_error,
            "fingerprint": digest,
            "contributors": project.contributors.all(),
            "parts": project.parts.all(),
            "agreements": project.agreements.all(),
            "contributor_wording": collaboration.wording("contributor"),
            "ownership_wording": collaboration.wording("ownership"),
        },
    )


@login_required
@require_http_methods(["POST"])
def collaboration_answer(request, pk):
    actor = actor_for(request)
    row = get_object_or_404(ProjectContributor, pk=pk, character=actor)
    answer = request.POST.get("answer")
    if answer not in {"accept", "decline", "leave"}:
        return HttpResponseBadRequest("Choose accept, decline or leave.")
    try:
        collaboration.answer(actor, row, accept=answer != "decline", leave=answer == "leave")
    except ValidationError as exc:
        return HttpResponseBadRequest(" ".join(exc.messages))
    return redirect("evennia_building:index")


class FrontierControlForm(forms.Form):
    action = forms.ChoiceField()
    room = forms.ModelChoiceField(queryset=None)
    text = forms.CharField(widget=forms.Textarea, max_length=50000)
    character = forms.IntegerField(
        min_value=1, required=False, label="New steward number (blank returns stewardship to staff)"
    )
    expected_steward = forms.IntegerField(
        min_value=1, required=False, label="Current steward number (blank when staff-held)"
    )
    reason = forms.CharField(widget=forms.Textarea, max_length=10000)
    frontiers = forms.ModelMultipleChoiceField(
        queryset=Frontier.objects.none(),
        required=False,
        label="Other frontier areas retired together",
    )
    properties = forms.ModelMultipleChoiceField(
        queryset=Property.objects.none(),
        required=False,
        label="Affected properties archived together",
    )
    replacements = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="Replacement connections",
        help_text="One source room number, target room number and compass direction per line.",
    )

    actions = {  # noqa: RUF012
        "description": ("Maintain description", ("room", "text")),
        "mood": ("Set temporary mood", ("room", "text")),
        "steward": (
            "Assign steward / record departure",
            ("room", "character", "expected_steward", "reason"),
        ),
        "relinquish": ("Relinquish my stewardship", ("room", "expected_steward", "reason")),
        "archive": (
            "Retire with a coordinated plan",
            ("frontiers", "properties", "replacements", "reason"),
        ),
        "restore": ("Restore preserved frontier group", ("reason",)),
    }

    def __init__(self, data=None, *, frontier, actor, actions, selected=None, **kwargs):
        super().__init__(data, **kwargs)
        self.fields["room"].queryset = (
            frontier.rooms.all() if is_staff(actor) else frontier.rooms.filter(steward=actor)
        )
        self.fields["room"].label_from_instance = lambda row: (
            f"{row.room.key if row.room else 'Missing'} (#{row.object_id})"
        )
        self.fields["frontiers"].queryset = Frontier.objects.filter(state="live").exclude(
            pk=frontier.pk
        )
        self.fields["frontiers"].label_from_instance = lambda row: row.name
        self.fields["properties"].queryset = Property.objects.filter(state="live")
        self.fields["properties"].label_from_instance = lambda row: f"{row.name} ({row.owner_name})"
        self.action_choices = [(key, self.actions[key][0]) for key in actions]
        selected = (data.get("action") if data is not None else selected) or actions[0]
        self.selected_action = selected
        self.fields["action"].choices = self.action_choices
        self.fields["action"].widget = forms.HiddenInput()
        self.fields["action"].initial = selected
        keep = self.actions.get(selected, ("", ()))[1]
        for name in list(self.fields):
            if name != "action" and name not in keep:
                del self.fields[name]


@login_required
@require_http_methods(["GET", "POST"])
def frontier_detail(request, pk):
    actor = actor_for(request)
    item = get_object_or_404(
        Frontier.objects.all() if is_staff(actor) else Frontier.objects.filter(state="live"), pk=pk
    )
    actions = []
    if item.state == "live":
        if is_staff(actor) or item.rooms.filter(steward=actor).exists():
            actions += ["description", "mood"]
        if item.rooms.filter(steward=actor).exists():
            actions += ["relinquish"]
        if is_staff(actor):
            actions += ["steward", "archive"]
    elif is_staff(actor):
        actions += ["restore"]
    form = (
        FrontierControlForm(
            request.POST if request.method == "POST" else None,
            frontier=item,
            actor=actor,
            actions=actions,
            selected=request.GET.get("action"),
        )
        if actions
        else None
    )
    if request.method == "POST":
        if form is None:
            raise PermissionDenied("No frontier maintenance action is available to this character.")
        if form.is_valid():
            try:
                values = form.cleaned_data
                action = values["action"]
                if action in {"description", "mood"}:
                    frontier.edit_room(actor, values["room"].room, **{action: values["text"]})
                elif action in {"steward", "relinquish"}:
                    frontier.set_steward(
                        actor,
                        values["room"],
                        ObjectDB.objects.get(pk=values["character"])
                        if values.get("character")
                        else None,
                        expected_steward=values["expected_steward"],
                        reason=values["reason"],
                    )
                elif action == "archive":
                    replacements = []
                    for line in values["replacements"].splitlines():
                        if line.strip():
                            source, target, direction = line.split()
                            replacements.append(
                                {
                                    "source": int(source),
                                    "target": int(target),
                                    "direction": direction,
                                }
                            )
                    frontier_lifecycle.archive(
                        actor,
                        item,
                        reason=values["reason"],
                        affected_frontiers=values["frontiers"],
                        affected_properties=values["properties"],
                        replacements=replacements,
                    )
                else:
                    frontier_lifecycle.restore(actor, item, reason=values["reason"])
                return redirect("evennia_building:frontier", pk=item.pk)
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
        "evennia_building/frontier.html",
        {
            "frontier": item,
            "rooms": item.rooms.select_related("room", "steward"),
            "form": form,
            "audit": item.audit.all() if is_staff(actor) else (),
        },
    )


@login_required
@require_http_methods(["GET"])
def frontier_index(request):
    actor = actor_for(request)
    items = Frontier.objects.filter(state="live").order_by("created_at", "pk")
    since = request.GET.get("since", "")
    error = ""
    try:
        cutoff = date.fromisoformat(since) if since else None
    except ValueError:
        cutoff, error = None, "Choose a valid promotion date."
    tiles, planes, selected_plane = [], [], None
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import RoomTile
        from evennia_maps.permissions import is_room_web_visible

        rows = list(
            RoomTile.objects.filter(
                room_id__in=FrontierRoom.objects.filter(frontier__state="live").values_list(
                    "object_id", flat=True
                ),
                plane__is_archived=False,
            ).select_related("plane", "room")
        )
        planes = sorted({row.plane for row in rows}, key=lambda plane: plane.name)
        try:
            selected_plane = next(
                (plane for plane in planes if plane.pk == int(request.GET.get("plane", 0))),
                planes[0] if planes else None,
            )
        except ValueError:
            selected_plane = planes[0] if planes else None
        dates = {
            row.object_id: row.frontier.created_at.date()
            for row in FrontierRoom.objects.filter(frontier__state="live").select_related(
                "frontier"
            )
        }
        if selected_plane:
            for row in RoomTile.objects.filter(plane=selected_plane).select_related("room"):
                if is_room_web_visible(row.room, actor):
                    tiles.append(
                        {
                            "id": row.room_id,
                            "name": row.room_name,
                            "x": row.x,
                            "y": row.y,
                            "new": row.room_id in dates
                            and (not cutoff or dates[row.room_id] >= cutoff),
                        }
                    )
    if tiles:
        min_x, max_x = min(row["x"] for row in tiles), max(row["x"] for row in tiles)
        min_y, max_y = min(row["y"] for row in tiles), max(row["y"] for row in tiles)
        for row in tiles:
            row["svg_x"], row["svg_y"] = (row["x"] - min_x) * 32 + 2, (max_y - row["y"]) * 32 + 2
        width, height = (max_x - min_x + 1) * 32 + 4, (max_y - min_y + 1) * 32 + 4
    else:
        width, height = 0, 0
    return render(
        request,
        "evennia_building/frontier_index.html",
        {
            "frontiers": items,
            "since": since,
            "error": error,
            "planes": planes,
            "selected_plane": selected_plane,
            "tiles": tiles,
            "width": width,
            "height": height,
        },
    )
