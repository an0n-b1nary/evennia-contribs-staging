# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for evennia_scenes. Requires [web] extra.

Read-only:
    /scenes/                              SceneListView
    /scenes/<pk>/                         SceneDetailView
    /scenes/<pk>/log/<entry_id>/history/  LogEntryHistoryView
    /scenes/<pk>/log/<entry_id>/diff/<ver>/  LogEntryDiffView

Authoring (login + active puppet required):
    /scenes/<pk>/log/<entry_id>/edit/     LogEntryEditView

Permission rules:
    - View-private scenes: only invited participants or staff can view.
    - LogEntryEditView: author or staff (SCENES_STAFF_LOCK) may edit.
    - Edits snapshot old content via LogEntryVersion before mutating.

Wire into your game's URLconf::

    from django.urls import include, path
    urlpatterns += [path("", include(("evennia_scenes.urls", "evennia_scenes")))]
"""

import difflib

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView, TemplateView
from evennia.objects.models import ObjectDB

from evennia_scenes.authoring import ScenesAuthoringMixin
from evennia_scenes.forms import LogEntryEditForm
from evennia_scenes.models import LogEntry, LogEntryVersion, Scene, SceneParticipant
from evennia_scenes.permissions import get_character_id, is_staff_user

ENTRIES_PER_PAGE = 25
VERSIONS_PER_PAGE = 20


def _can_view_scene(scene, request):
    """Return True if the request may view this scene."""
    if scene.privacy != Scene.Privacy.VIEW_PRIVATE:
        return True
    if is_staff_user(request):
        return True
    character_id = get_character_id(request.user)
    if character_id is None:
        return False
    return SceneParticipant.objects.filter(
        scene=scene, character_id=character_id, is_invited=True
    ).exists()


class SceneListView(ListView):
    """Paginated list of closed public scenes."""

    model = Scene
    template_name = "evennia_scenes/scene_list.html"
    context_object_name = "scenes"
    paginate_by = 20

    def get_queryset(self):
        return Scene.objects.filter(
            status=Scene.Status.CLOSED,
            privacy__in=[Scene.Privacy.PUBLIC, Scene.Privacy.POSE_PRIVATE],
        ).order_by("-ended_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Scene Archive"
        return context


class SceneDetailView(DetailView):
    """Scene detail showing log entries with pagination."""

    model = Scene
    template_name = "evennia_scenes/scene_detail.html"
    context_object_name = "scene"

    def get_object(self, queryset=None):
        scene = get_object_or_404(Scene.all_objects, pk=self.kwargs["pk"])
        if not _can_view_scene(scene, self.request):
            raise PermissionDenied("This scene is private.")
        return scene

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scene = self.object
        context["page_title"] = scene.title or f"Scene #{scene.pk}"

        qs = scene.log_entries.filter(is_deleted=False).order_by("order", "created_at")
        paginator = Paginator(qs, ENTRIES_PER_PAGE)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
        context["page_obj"] = page_obj
        context["log_entries"] = page_obj.object_list
        context["participants"] = scene.participants.all()
        context["is_staff"] = is_staff_user(self.request)
        context["character_id"] = get_character_id(self.request.user)
        return context


class LogEntryEditView(ScenesAuthoringMixin, FormView):
    """Edit a log entry. Snapshots old content in LogEntryVersion before saving."""

    form_class = LogEntryEditForm
    template_name = "evennia_scenes/log_edit_form.html"

    def _get_entry(self):
        if not hasattr(self, "_entry"):
            self._entry = get_object_or_404(
                LogEntry,
                pk=self.kwargs["entry_id"],
                scene_id=self.kwargs["pk"],
                is_deleted=False,
            )
        return self._entry

    def get_permission_target(self):
        return self._get_entry()

    def check_permission(self, character_id, target):
        if target.author_id != character_id and not is_staff_user(self.request):
            raise PermissionDenied("You can only edit your own log entries.")
        if target.scene.is_archived:
            raise PermissionDenied("Cannot edit entries in an archived scene.")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_entry()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._get_entry()
        context["entry"] = entry
        context["scene"] = entry.scene
        context["page_title"] = f"Edit Log Entry #{entry.pk}"
        context["cancel_url"] = reverse(
            "evennia_scenes:scene-detail", kwargs={"pk": entry.scene_id}
        )
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        entry = self._get_entry()
        character = get_object_or_404(ObjectDB, pk=character_id)
        # Snapshot pre-edit content before mutating.
        old_content = LogEntry.objects.values_list("content", flat=True).get(pk=entry.pk)
        LogEntryVersion.create_version(parent=entry, content=old_content, editor=character)
        entry.content = form.cleaned_data["content"]
        entry.save(update_fields=["content"])
        return HttpResponseRedirect(
            reverse("evennia_scenes:scene-detail", kwargs={"pk": entry.scene_id})
        )


class LogEntryHistoryView(TemplateView):
    """Version history for a log entry."""

    template_name = "evennia_scenes/log_history.html"

    def get(self, request, *args, **kwargs):
        entry = get_object_or_404(LogEntry, pk=self.kwargs["entry_id"], scene_id=self.kwargs["pk"])
        scene = entry.scene
        if not _can_view_scene(scene, request):
            raise PermissionDenied("This scene is private.")
        self._entry = entry
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._entry
        qs = LogEntryVersion.objects.filter(parent=entry).order_by("-version_number")
        paginator = Paginator(qs, VERSIONS_PER_PAGE)
        page_obj = paginator.get_page(self.request.GET.get("page", 1))
        context["entry"] = entry
        context["scene"] = entry.scene
        context["page_obj"] = page_obj
        context["versions"] = page_obj.object_list
        context["page_title"] = f"Edit History — Log Entry #{entry.pk}"
        context["is_staff"] = is_staff_user(self.request)
        return context


class LogEntryDiffView(TemplateView):
    """Inline diff of a log entry against one of its versions."""

    template_name = "evennia_scenes/log_diff.html"

    def get(self, request, *args, **kwargs):
        entry = get_object_or_404(LogEntry, pk=self.kwargs["entry_id"], scene_id=self.kwargs["pk"])
        scene = entry.scene
        if not _can_view_scene(scene, request):
            raise PermissionDenied("This scene is private.")
        version = get_object_or_404(
            LogEntryVersion,
            parent=entry,
            version_number=self.kwargs["version_number"],
        )
        self._entry = entry
        self._version = version
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._entry
        version = self._version

        old_lines = version.content.splitlines(keepends=True)
        new_lines = entry.content.splitlines(keepends=True)
        diff_html = difflib.HtmlDiff().make_table(
            old_lines,
            new_lines,
            fromdesc=f"v{version.version_number}",
            todesc="current",
            context=True,
            numlines=3,
        )
        context["entry"] = entry
        context["scene"] = entry.scene
        context["version"] = version
        context["diff_html"] = diff_html
        context["page_title"] = f"Diff — Log Entry #{entry.pk} vs v{version.version_number}"
        return context
