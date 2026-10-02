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

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.text import slugify
from django.views.generic import DetailView, FormView, ListView, TemplateView
from evennia.objects.models import ObjectDB

from evennia_scenes.authoring import ScenesAuthoringMixin
from evennia_scenes.forms import LogEntryEditForm
from evennia_scenes.models import LogEntry, LogEntryVersion, Scene, SceneParticipant
from evennia_scenes.permissions import get_character_id, is_staff_user

ENTRIES_PER_PAGE = 25
VERSIONS_PER_PAGE = 20


def _can_view_scene(scene, request):
    """Return True if the request may view this scene.

    Web-readable tiers are world-readable; every other tier is visible only
    to staff and invited participants.

    Asks Scene.is_web_readable() rather than testing != VIEW_PRIVATE. The two
    agree only while there are exactly three tiers, and this predicate gates
    SceneDetailView plus the log history/diff drill-downs — of the two ways
    to be wrong about a tier added later, serving it is the bad one.
    """
    if Scene.is_web_readable(scene.privacy):
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
            privacy__in=Scene.WEB_READABLE_PRIVACY,
        ).order_by("-ended_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Scene Archive"
        return context


class SceneLiveListView(SceneListView):
    """Public scenes happening now, separate from the finished archive."""

    def get_queryset(self):
        return Scene.objects.filter(
            status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE),
            privacy__in=Scene.WEB_READABLE_PRIVACY,
        ).order_by("-started_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Happening Now", live_list=True)
        return context


class SceneDetailView(DetailView):
    """Scene detail showing log entries with pagination."""

    model = Scene
    template_name = "evennia_scenes/scene_detail.html"
    context_object_name = "scene"

    def get_object(self, queryset=None):
        # The manager excludes archived scenes; privacy applies at every status
        # and on every poll, using the same fail-closed membership predicate.
        scene = get_object_or_404(Scene.objects, pk=self.kwargs["pk"])
        if not _can_view_scene(scene, self.request):
            raise PermissionDenied("This scene is private.")
        return scene

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get("poll") == "1":
            response = JsonResponse(
                {
                    "html": render_to_string(
                        "evennia_scenes/_scene_reading.html", context, request=self.request
                    ),
                    "live": context["is_live"],
                }
            )
        else:
            response = super().render_to_response(context, **response_kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scene = self.object
        context["page_title"] = scene.title or "Untitled Scene"

        # Both in-room OOC and web-viewer OOC are excluded by default so the
        # public log reads as IC; ?include_ooc=1 surfaces them.
        qs = scene.log_entries.filter(is_deleted=False)
        include_ooc = self.request.GET.get("include_ooc") == "1"
        if not include_ooc:
            qs = qs.exclude(log_type__in=[LogEntry.LogType.OOC, LogEntry.LogType.WEB_OOC])
        qs = qs.order_by("order", "created_at")

        paginator = Paginator(qs, ENTRIES_PER_PAGE)
        context["is_live"] = scene.status in (Scene.Status.OPEN, Scene.Status.ACTIVE)
        page_number = self.request.GET.get("page")
        if page_number is None or page_number == "latest":
            page_number = (
                paginator.num_pages if context["is_live"] or page_number == "latest" else 1
            )
        page_obj = paginator.get_page(page_number)
        context["page_obj"] = page_obj
        context["log_entries"] = page_obj.object_list
        context["include_ooc"] = include_ooc
        participants = list(scene.participants.select_related("character"))
        for participant in participants:
            participant.character_url = ""
            character = participant.character
            if character is not None:
                try:
                    if character.access(self.request.user, "view"):
                        participant.character_url = reverse(
                            "character-detail",
                            kwargs={"slug": slugify(character.key), "pk": character.pk},
                        )
                except (AttributeError, NoReverseMatch):
                    pass
        context["participants"] = participants
        context.update(_related_scene_links(scene))
        context["room_label"] = scene.room_name or "Not recorded"
        if _room_is_visible(scene.room, self.request):
            context["room_url"] = _room_url(scene.room)
        else:
            context["room_url"] = ""
            context["room_label"] = "Location unavailable"
        context["is_staff"] = is_staff_user(self.request)
        context["character_id"] = get_character_id(self.request.user)
        return context


def _room_is_visible(room, request):
    """Use the installed regions policy for both room labels and links."""
    if room is None or is_staff_user(request):
        return True
    if apps.is_installed(getattr(settings, "SCENES_REGIONS_APP_LABEL", "evennia_regions")):
        try:
            from evennia_regions.permissions import is_room_web_visible

            return is_room_web_visible(room)
        except (ImportError, LookupError):
            return False
    return True


def _room_url(room):
    """Return the optional destination for a room whose visibility was checked."""
    if room is None:
        return ""
    try:
        return reverse("evennia_regions:room-detail", kwargs={"pk": room.pk})
    except NoReverseMatch:
        return ""


def _related_scene_links(scene):
    """Resolve optional lore, plot, and calendar bridges without hard imports."""
    context = {"linked_lore": [], "linked_plots": [], "linked_events": []}
    try:
        lore_label = getattr(settings, "SCENES_LORE_APP_LABEL", "evennia_lore")
        lore_link = apps.get_model(lore_label, "LoreSceneLink")
        lore_entry = apps.get_model(lore_label, "LoreEntry")
        entry_ids = lore_link.objects.filter(scene_id=scene.pk).values_list("entry_id", flat=True)
        entries = list(
            lore_entry.objects.filter(
                pk__in=entry_ids, status=lore_entry.Status.PUBLISHED, is_archived=False
            ).order_by("entry_number")
        )
        for entry in entries:
            try:
                entry.entry_url = reverse("lore-detail", kwargs={"pk": entry.pk})
            except NoReverseMatch:
                entry.entry_url = ""
        context["linked_lore"] = entries
    except (LookupError, ValueError):
        pass

    try:
        plot_label = getattr(settings, "SCENES_PLOTS_APP_LABEL", "evennia_plots")
        plot_link = apps.get_model(plot_label, "ScenePlotLink")
        plot_thread = apps.get_model(plot_label, "PlotThread")
        thread_ids = plot_link.objects.filter(scene_id=scene.pk).values_list("thread_id", flat=True)
        threads = plot_thread.objects.filter(pk__in=thread_ids).exclude(
            privacy=plot_thread.Privacy.PRIVATE
        )
        threads = list(threads.order_by("name"))
        for thread in threads:
            try:
                thread.thread_url = reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk})
            except NoReverseMatch:
                thread.thread_url = ""
        context["linked_plots"] = threads
    except (LookupError, ValueError):
        pass

    try:
        calendar_label = getattr(settings, "SCENES_CALENDAR_APP_LABEL", "evennia_calendar")
        calendar_link = apps.get_model(calendar_label, "SceneCalendarLink")
        event_model = apps.get_model(calendar_label, "CalendarEvent")
        event_ids = calendar_link.objects.filter(scene_id=scene.pk).values_list(
            "event_id", flat=True
        )
        events = list(
            event_model.objects.filter(pk__in=event_ids, is_cancelled=False).order_by(
                "scheduled_time"
            )
        )
        for event in events:
            try:
                event.event_url = reverse(
                    "evennia_calendar:calendar-event-detail", kwargs={"pk": event.pk}
                )
            except NoReverseMatch:
                event.event_url = ""
        context["linked_events"] = events
    except (LookupError, ValueError):
        pass
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
        context["page_title"] = "Edit Log Entry"
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
        context["page_title"] = "Edit History — Log Entry"
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

        # Colorblind-safe diff: each line carries a +/- text prefix (from
        # unified_diff) AND a CSS class, so meaning never relies on color alone.
        old_lines = version.content.splitlines(keepends=True)
        new_lines = entry.content.splitlines(keepends=True)
        raw_diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"v{version.version_number}",
                tofile="current",
                lineterm="",
            )
        )

        diff_lines = []
        for line in raw_diff:
            if line.startswith(("+++", "---")):
                css = "evennia-scenes-diff-meta"
            elif line.startswith("@@"):
                css = "evennia-scenes-diff-hunk"
            elif line.startswith("+"):
                css = "evennia-scenes-diff-add"
            elif line.startswith("-"):
                css = "evennia-scenes-diff-remove"
            else:
                css = "evennia-scenes-diff-context"
            diff_lines.append((css, line))

        context["entry"] = entry
        context["scene"] = entry.scene
        context["version"] = version
        context["diff_lines"] = diff_lines
        context["no_diff"] = not raw_diff
        context["page_title"] = f"Diff — Log Entry vs v{version.version_number}"
        return context
