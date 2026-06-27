# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for the evennia_plots contrib.

Read-only views:
    PlotListView            — /plots/           thread list with tag filter
    PlotDetailView          — /plots/<pk>/      thread detail with IC updates
    PlotArcListView         — /plots/arcs/      staff-only arc list with filters
    PlotArcDetailView       — /plots/arc/<pk>/  arc with IC updates + member threads
    PlotTagListView         — /plots/tags/      tag index

Authoring views:
    PlotCreateView          — /plots/new/
    PlotEditView            — /plots/<pk>/edit/
    PlotInviteView          — /plots/<pk>/invite/
    PlotUpdateCreateView    — /plots/<pk>/updates/new/
    PlotUpdateEditView      — /plots/<pk>/updates/<update_id>/edit/
    PlotUpdateHistoryView   — /plots/<pk>/updates/<update_id>/history/
    PlotUpdateDiffView      — /plots/<pk>/updates/<update_id>/diff/<version_number>/
    PlotTagCreateView       — /plots/tags/new/
    PlotArcCreateView       — /plots/arc/new/
    PlotArcEditView         — /plots/arc/<pk>/edit/
    PlotArcSetCurrentView   — /plots/arc/<pk>/set-current/   (POST only)
    PlotArcClearCurrentView — /plots/arc/<pk>/clear-current/ (POST only)
"""

import difflib

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView
from evennia.objects.models import ObjectDB

from evennia_plots.authoring import AuthoringMixin
from evennia_plots.forms import (
    PlotArcCreateForm,
    PlotArcEditForm,
    PlotInviteForm,
    PlotTagCreateForm,
    PlotThreadCreateForm,
    PlotThreadEditForm,
    PlotUpdateEditForm,
    PlotUpdateForm,
)
from evennia_plots.models import (
    PlotArc,
    PlotTag,
    PlotThread,
    PlotUpdate,
    PlotUpdateVersion,
)
from evennia_plots.permissions import can_manage_arc, get_character_id, is_staff_user
from evennia_plots.signals import arc_currency_changed, arc_type_changed

# ---------------------------------------------------------------------------
# Read-only views
# ---------------------------------------------------------------------------


class PlotListView(ListView):
    """Paginated list of active public plot threads, with optional tag filter."""

    model = PlotThread
    template_name = "evennia_plots/plot_list.html"
    context_object_name = "threads"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            PlotThread.objects.filter(
                status=PlotThread.Status.ACTIVE,
                privacy__in=[PlotThread.Privacy.PUBLIC, PlotThread.Privacy.INVITE_ONLY],
            )
            .prefetch_related("tags")
            .order_by("-created_at")
        )
        tag = self.request.GET.get("tag", "").strip()
        if tag:
            qs = qs.filter(tags__name__icontains=tag).distinct()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Plot Threads"
        context["tag_filter"] = self.request.GET.get("tag", "")
        context["all_major_tags"] = PlotTag.objects.filter(is_major=True).order_by("name")
        return context


class PlotDetailView(DetailView):
    """Detail view for a single plot thread."""

    model = PlotThread
    template_name = "evennia_plots/plot_detail.html"
    context_object_name = "thread"

    def get_queryset(self):
        return PlotThread.objects.exclude(privacy=PlotThread.Privacy.PRIVATE)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self.object
        context["page_title"] = f"Plot Thread: {thread.name}"

        context["updates"] = thread.updates.filter(update_type="ic").order_by("created_at")

        # Soft-ref partner resolution — each partner is optional.
        # Scene/Post use all_objects when available (follows through archived rows).
        try:
            from evennia_scenes.models import Scene

            scene_links_qs = list(thread.scene_links.order_by("created_at"))
            scene_manager = getattr(Scene, "all_objects", Scene.objects)
            scenes_by_id = scene_manager.in_bulk(lk.scene_id for lk in scene_links_qs)
            scene_link_list = []
            for lk in scene_links_qs:
                scene = scenes_by_id.get(lk.scene_id)
                if scene:
                    lk.scene = scene
                    scene_link_list.append(lk)
            context["scene_links"] = scene_link_list
        except ImportError:
            context["scene_links"] = []

        try:
            from evennia_calendar.models import CalendarEvent

            event_links_qs = list(thread.calendar_links.order_by("created_at"))
            events_by_id = CalendarEvent.objects.in_bulk(lk.event_id for lk in event_links_qs)
            event_link_list = []
            for lk in event_links_qs:
                event = events_by_id.get(lk.event_id)
                if event:
                    lk.event = event
                    event_link_list.append(lk)
            context["event_links"] = event_link_list
        except ImportError:
            context["event_links"] = []

        try:
            from evennia_boards.models import Post

            board_links_qs = list(thread.board_links.order_by("created_at"))
            post_manager = getattr(Post, "all_objects", Post.objects)
            posts_by_id = post_manager.select_related("board").in_bulk(
                lk.post_id for lk in board_links_qs
            )
            board_link_list = []
            for lk in board_links_qs:
                post = posts_by_id.get(lk.post_id)
                if post:
                    lk.post = post
                    board_link_list.append(lk)
            context["board_links"] = board_link_list
        except ImportError:
            context["board_links"] = []

        context["participants"] = thread.participants.filter(is_active=True).order_by(
            "character_name"
        )

        context["sequels"] = thread.outgoing_links.filter(
            link_type="sequel", is_accepted=True
        ).select_related("to_thread")
        context["related_threads"] = list(
            thread.outgoing_links.filter(link_type="related", is_accepted=True).select_related(
                "to_thread"
            )
        ) + list(
            thread.incoming_links.filter(link_type="related", is_accepted=True).select_related(
                "from_thread"
            )
        )

        context["is_staff"] = is_staff_user(self.request)
        context["character_id"] = get_character_id(self.request.user)
        return context


class PlotArcDetailView(DetailView):
    """Detail view for a plot arc showing IC updates and member threads."""

    model = PlotArc
    template_name = "evennia_plots/plot_arc_detail.html"
    context_object_name = "arc"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        arc = self.object
        staff = is_staff_user(self.request)
        character_id = get_character_id(self.request.user)
        context["page_title"] = f"Plot Arc: {arc.name}"

        updates_qs = arc.updates.order_by("created_at")
        if not staff:
            updates_qs = updates_qs.filter(update_type="ic")
        context["updates"] = updates_qs

        threads_qs = arc.threads.prefetch_related("tags").order_by("status", "-created_at")
        if not staff:
            threads_qs = threads_qs.filter(
                privacy__in=[PlotThread.Privacy.PUBLIC, PlotThread.Privacy.INVITE_ONLY],
            )
        context["threads"] = threads_qs

        context["is_staff"] = staff
        context["pauses_xp"] = arc.pauses_xp
        context["is_current"] = arc.is_current
        context["can_manage"] = staff and can_manage_arc(
            ObjectDB.objects.filter(pk=character_id).first() if character_id else None,
            arc,
        )

        xp_overrides = {}
        for source in PlotArc.XP_SOURCES:
            override = getattr(arc, f"xp_mult_{source}")
            if override is not None:
                xp_overrides[source] = {
                    "label": PlotArc.XP_SOURCE_LABELS[source],
                    "override": override,
                    "type_default": PlotArc.TYPE_DEFAULT_MULTIPLIERS[arc.arc_type][source],
                }
        context["xp_overrides"] = xp_overrides

        return context


class PlotTagListView(TemplateView):
    """Browsable tag index: major tags first, then minor tags with counts."""

    template_name = "evennia_plots/plot_tags.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Plot Tags"

        major = []
        minor = []
        for tag in PlotTag.objects.prefetch_related("threads", "arcs").order_by("name"):
            thread_count = tag.threads.filter(
                status=PlotThread.Status.ACTIVE,
                privacy__in=[PlotThread.Privacy.PUBLIC, PlotThread.Privacy.INVITE_ONLY],
            ).count()
            arc_count = tag.arcs.count()
            entry = {"tag": tag, "thread_count": thread_count, "arc_count": arc_count}
            if tag.is_major:
                major.append(entry)
            else:
                minor.append(entry)

        context["major_tags"] = major
        context["minor_tags"] = minor
        context["is_staff"] = is_staff_user(self.request)
        return context


# ---------------------------------------------------------------------------
# Authoring views
# ---------------------------------------------------------------------------


class PlotTagCreateView(AuthoringMixin, FormView):
    """Create a new canonical (major) PlotTag. Builder+ only.

    Minor tags are created implicitly via the in-game +plot/tag command.
    This view produces major canonical tags only.
    """

    form_class = PlotTagCreateForm
    template_name = "evennia_plots/plot_tag_create_form.html"

    def check_permission(self, character_id, target):
        if not is_staff_user(self.request):
            raise PermissionDenied("Only staff may create canonical tags.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Plot Tag (Major)"
        context["major_tags"] = PlotTag.objects.filter(is_major=True).order_by("name")
        context["form_action"] = reverse("evennia_plots:plot-tag-create")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        tag = form.save(commit=False)
        tag.is_major = True
        tag.created_by = character
        tag.created_by_name = character.key
        tag.save()
        return HttpResponseRedirect(reverse("evennia_plots:plot-tag-create"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotCreateView(AuthoringMixin, FormView):
    """Create a new plot thread. Any logged-in character may create."""

    form_class = PlotThreadCreateForm
    template_name = "evennia_plots/plot_form.html"

    def check_permission(self, character_id, target):
        pass  # any puppet holder can create

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Start a New Plot Thread"
        context["form_action"] = reverse("evennia_plots:plot-create")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        thread = PlotThread.create_thread(
            name=form.cleaned_data["name"],
            creator=character,
            description=form.cleaned_data.get("description", ""),
            privacy=form.cleaned_data["privacy"],
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotEditView(AuthoringMixin, FormView):
    """Edit an existing thread's name, description, or privacy.

    Permission: creator or staff.
    """

    form_class = PlotThreadEditForm
    template_name = "evennia_plots/plot_edit_form.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def get_permission_target(self):
        return self._get_thread()

    def check_permission(self, character_id, target):
        thread = target
        if is_staff_user(self.request):
            return
        if thread.creator_id and thread.creator_id == character_id:
            return
        raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_thread()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        context["page_title"] = f"Edit Plot Thread: {thread.name}"
        context["thread"] = thread
        context["form_action"] = reverse("evennia_plots:plot-edit", kwargs={"pk": thread.pk})
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        thread = self._get_thread()
        thread.edit(
            editor=character,
            name=form.cleaned_data["name"],
            description=form.cleaned_data.get("description", ""),
            privacy=form.cleaned_data["privacy"],
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotInviteView(AuthoringMixin, FormView):
    """Toggle invited characters on an invite-only thread.

    Permission: creator or staff. The form takes a character name string;
    the view resolves it to an ObjectDB instance.
    """

    form_class = PlotInviteForm
    template_name = "evennia_plots/plot_invite_form.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def get_permission_target(self):
        return self._get_thread()

    def check_permission(self, character_id, target):
        thread = target
        if is_staff_user(self.request):
            return
        if thread.creator_id and thread.creator_id == character_id:
            return
        raise PermissionDenied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        context["page_title"] = f"Manage Invites: {thread.name}"
        context["thread"] = thread
        context["invited"] = thread.invited_characters.order_by("db_key")
        context["form_action"] = reverse("evennia_plots:plot-invite", kwargs={"pk": thread.pk})
        return context

    def form_valid(self, form):
        thread = self._get_thread()
        char_name = form.cleaned_data["character_name"].strip()
        action = form.cleaned_data["action"]

        target_char = ObjectDB.objects.filter(db_key__iexact=char_name).first()
        if target_char is None:
            form.add_error("character_name", f"No character named '{char_name}' found.")
            return self.form_invalid(form)

        if action == "invite":
            thread.invited_characters.add(target_char)
        else:
            thread.invited_characters.remove(target_char)

        return HttpResponseRedirect(reverse("evennia_plots:plot-invite", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotUpdateCreateView(AuthoringMixin, FormView):
    """Append a new PlotUpdate block to a thread.

    Permission: thread.can_update(character) — thread must be ACTIVE and
    character must be a participant, invited character, or staff.
    """

    form_class = PlotUpdateForm
    template_name = "evennia_plots/plot_update_form.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def get_permission_target(self):
        return self._get_thread()

    def check_permission(self, character_id, target):
        thread = target
        character = get_object_or_404(ObjectDB, pk=character_id)
        if not thread.can_update(character):
            raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Pre-seed instance so PlotUpdate.clean() sees thread set and passes validation.
        kwargs["instance"] = PlotUpdate(thread=self._get_thread())
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        context["page_title"] = f"Add Update: {thread.name}"
        context["thread"] = thread
        context["form_action"] = reverse(
            "evennia_plots:plot-update-create", kwargs={"pk": thread.pk}
        )
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        thread = self._get_thread()
        PlotUpdate.create_update(
            parent=thread,
            author=character,
            content=form.cleaned_data["content"],
            update_type=form.cleaned_data.get("update_type", "ic"),
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotUpdateEditView(AuthoringMixin, FormView):
    """Edit an existing PlotUpdate block, snapshotting the old content first.

    Permission: update author or staff.
    """

    form_class = PlotUpdateEditForm
    template_name = "evennia_plots/plot_update_edit_form.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def _get_update(self):
        if not hasattr(self, "_update"):
            self._update = get_object_or_404(
                PlotUpdate, pk=self.kwargs["update_id"], thread=self._get_thread()
            )
        return self._update

    def get_permission_target(self):
        return self._get_update()

    def check_permission(self, character_id, target):
        update = target
        if is_staff_user(self.request):
            return
        if update.author_id and update.author_id == character_id:
            return
        raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_update()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        update = self._get_update()
        context["page_title"] = f"Edit Update — {thread.name}"
        context["thread"] = thread
        context["update"] = update
        context["form_action"] = reverse(
            "evennia_plots:plot-update-edit",
            kwargs={"pk": thread.pk, "update_id": update.pk},
        )
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        update = self._get_update()
        # Re-fetch old content from DB before ModelForm mutates the instance.
        old_content = PlotUpdate.objects.values_list("content", flat=True).get(pk=update.pk)
        PlotUpdateVersion.create_version(parent=update, content=old_content, editor=character)
        update.content = form.cleaned_data["content"]
        update.update_type = form.cleaned_data.get("update_type", update.update_type)
        update.edited_at = timezone.now()
        update.save(update_fields=["content", "update_type", "edited_at"])
        return HttpResponseRedirect(
            reverse("evennia_plots:plot-detail", kwargs={"pk": self._get_thread().pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotUpdateHistoryView(TemplateView):
    """Public list of version snapshots for a PlotUpdate block."""

    template_name = "evennia_plots/plot_update_history.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def _get_update(self):
        if not hasattr(self, "_update"):
            self._update = get_object_or_404(
                PlotUpdate, pk=self.kwargs["update_id"], thread=self._get_thread()
            )
        return self._update

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        update = self._get_update()
        context["page_title"] = f"Update History — {thread.name}"
        context["thread"] = thread
        context["update"] = update
        context["versions"] = PlotUpdateVersion.objects.filter(parent=update).order_by(
            "-version_number"
        )
        return context


class PlotUpdateDiffView(TemplateView):
    """Unified diff between a version snapshot and the current PlotUpdate content."""

    template_name = "evennia_plots/plot_update_diff.html"

    def _get_thread(self):
        if not hasattr(self, "_thread"):
            self._thread = get_object_or_404(PlotThread, pk=self.kwargs["pk"])
        return self._thread

    def _get_update(self):
        if not hasattr(self, "_update"):
            self._update = get_object_or_404(
                PlotUpdate, pk=self.kwargs["update_id"], thread=self._get_thread()
            )
        return self._update

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        update = self._get_update()
        version = get_object_or_404(
            PlotUpdateVersion,
            parent=update,
            version_number=self.kwargs["version_number"],
        )

        old_lines = version.content.splitlines(keepends=True)
        new_lines = update.content.splitlines(keepends=True)
        raw_diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"v{version.version_number}",
                tofile="current",
            )
        )

        diff_lines = []
        for line in raw_diff:
            if line.startswith("+++") or line.startswith("---"):
                css = "diff-meta"
            elif line.startswith("@@"):
                css = "diff-hunk"
            elif line.startswith("+"):
                css = "diff-add"
            elif line.startswith("-"):
                css = "diff-remove"
            else:
                css = "diff-context"
            diff_lines.append((css, line))

        context["page_title"] = f"Diff v{version.version_number} — {thread.name}"
        context["thread"] = thread
        context["update"] = update
        context["version"] = version
        context["diff_lines"] = diff_lines
        context["no_diff"] = not diff_lines
        return context


# ---------------------------------------------------------------------------
# Arc authoring views
# ---------------------------------------------------------------------------


class PlotArcListView(AuthoringMixin, ListView):
    """Staff-only paginated list of all arcs with status and type filters."""

    model = PlotArc
    template_name = "evennia_plots/plot_arc_list.html"
    context_object_name = "arcs"
    paginate_by = 20

    def check_permission(self, character_id, target):
        if not is_staff_user(self.request):
            raise PermissionDenied

    def get_queryset(self):
        qs = PlotArc.objects.prefetch_related("tags").order_by("-created_at")
        status = self.request.GET.get("status", "").strip()
        arc_type = self.request.GET.get("arc_type", "").strip()
        if status:
            qs = qs.filter(status=status)
        if arc_type:
            qs = qs.filter(arc_type=arc_type)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Plot Arcs"
        context["is_staff"] = True
        context["status_filter"] = self.request.GET.get("status", "")
        context["arc_type_filter"] = self.request.GET.get("arc_type", "")
        context["status_choices"] = PlotArc.Status.choices
        context["arc_type_choices"] = PlotArc.ArcType.choices
        return context


class PlotArcCreateView(AuthoringMixin, FormView):
    """Create a new PlotArc. Builder+ only."""

    form_class = PlotArcCreateForm
    template_name = "evennia_plots/plot_arc_form.html"

    def check_permission(self, character_id, target):
        character = ObjectDB.objects.filter(pk=character_id).first() if character_id else None
        if not can_manage_arc(character):
            raise PermissionDenied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Plot Arc"
        context["form_action"] = reverse("evennia_plots:plot-arc-create")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        arc = PlotArc.create_arc(
            name=form.cleaned_data["name"],
            creator=character,
            description=form.cleaned_data.get("description", ""),
            arc_type=form.cleaned_data["arc_type"],
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-arc-detail", kwargs={"pk": arc.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotArcEditView(AuthoringMixin, FormView):
    """Edit an existing arc's name, description, arc_type, or XP multipliers. Builder+ only."""

    form_class = PlotArcEditForm
    template_name = "evennia_plots/plot_arc_form.html"

    def _get_arc(self):
        if not hasattr(self, "_arc"):
            self._arc = get_object_or_404(PlotArc, pk=self.kwargs["pk"])
        return self._arc

    def get_permission_target(self):
        return self._get_arc()

    def check_permission(self, character_id, target):
        character = ObjectDB.objects.filter(pk=character_id).first() if character_id else None
        if not can_manage_arc(character, target):
            raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_arc()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        arc = self._get_arc()
        context["page_title"] = f"Edit Arc: {arc.name}"
        context["arc"] = arc
        context["form_action"] = reverse("evennia_plots:plot-arc-edit", kwargs={"pk": arc.pk})
        return context

    def form_valid(self, form):
        arc = self._get_arc()
        # Fetch old_type before saving so we can fire the signal only on change.
        old_type = PlotArc.objects.values_list("arc_type", flat=True).get(pk=arc.pk)
        arc.name = form.cleaned_data["name"]
        arc.description = form.cleaned_data.get("description", "")
        arc.arc_type = form.cleaned_data["arc_type"]
        arc.xp_mult_rp_session = form.cleaned_data.get("xp_mult_rp_session")
        arc.xp_mult_cutscene = form.cleaned_data.get("xp_mult_cutscene")
        arc.xp_mult_lore = form.cleaned_data.get("xp_mult_lore")
        arc.xp_mult_thread_bonus = form.cleaned_data.get("xp_mult_thread_bonus")
        arc.save(
            update_fields=[
                "name",
                "description",
                "arc_type",
                "xp_mult_rp_session",
                "xp_mult_cutscene",
                "xp_mult_lore",
                "xp_mult_thread_bonus",
            ]
        )
        if old_type != arc.arc_type:
            arc_type_changed.send(
                sender=type(arc), arc=arc, old_type=old_type, new_type=arc.arc_type
            )
            if arc.arc_type == PlotArc.ArcType.DOWNTIME and arc.is_current:
                messages.warning(
                    self.request,
                    "XP is now paused gamewide — this arc is current and set to Downtime.",
                )
        return HttpResponseRedirect(reverse("evennia_plots:plot-arc-detail", kwargs={"pk": arc.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


def _resolve_arc_for_management(request, pk):
    """Fetch arc by pk and verify the request user has arc-management permission.

    Raises PermissionDenied if the user lacks Builder+ access. Returns the arc
    on success.
    """
    arc = get_object_or_404(PlotArc, pk=pk)
    character_id = get_character_id(request.user)
    character = ObjectDB.objects.filter(pk=character_id).first() if character_id else None
    if not can_manage_arc(character, arc):
        raise PermissionDenied
    return arc


class PlotArcSetCurrentView(LoginRequiredMixin, View):
    """POST-only view: promote an arc to global current, demoting any prior current.

    Builder+ only. Uses select_for_update inside a transaction to prevent
    two concurrent requests from creating two current arcs.
    """

    login_url = "/accounts/login/"
    http_method_names = ["post"]  # noqa: RUF012

    def post(self, request, *args, **kwargs):
        arc = _resolve_arc_for_management(request, kwargs["pk"])
        if arc.status != PlotArc.Status.ACTIVE:
            return HttpResponseBadRequest("Only Active arcs may be made current.")
        if arc.is_current:
            return HttpResponseRedirect(
                reverse("evennia_plots:plot-arc-detail", kwargs={"pk": arc.pk})
            )
        # Signal sends are deferred via transaction.on_commit so listeners
        # only see committed state — protects notifications listeners from
        # acting on a rolled-back demotion or promotion.
        with transaction.atomic():
            demoted = (
                PlotArc.objects.select_for_update()
                .filter(is_current=True)
                .exclude(pk=arc.pk)
                .first()
            )
            if demoted:
                demoted.is_current = False
                demoted.save(update_fields=["is_current"])
                transaction.on_commit(
                    lambda d=demoted: arc_currency_changed.send(
                        sender=type(d), arc=d, became_current=False
                    )
                )
            arc.is_current = True
            arc.save(update_fields=["is_current"])
            transaction.on_commit(
                lambda: arc_currency_changed.send(sender=type(arc), arc=arc, became_current=True)
            )
        return HttpResponseRedirect(reverse("evennia_plots:plot-arc-detail", kwargs={"pk": arc.pk}))


class PlotArcClearCurrentView(LoginRequiredMixin, View):
    """POST-only view: clear is_current on an arc (idempotent). Builder+ only."""

    login_url = "/accounts/login/"
    http_method_names = ["post"]  # noqa: RUF012

    def post(self, request, *args, **kwargs):
        arc = _resolve_arc_for_management(request, kwargs["pk"])
        if arc.is_current:
            arc.is_current = False
            arc.save(update_fields=["is_current"])
            arc_currency_changed.send(sender=type(arc), arc=arc, became_current=False)
        return HttpResponseRedirect(reverse("evennia_plots:plot-arc-detail", kwargs={"pk": arc.pk}))
