# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for the evennia_plots contrib.

Players call a PlotThread a "plot" and a StoryThread a "thread".

Read-only views:
    PlotListView            — /plots/           plot list with tag filter
    PlotDetailView          — /plots/<pk>/      plot detail with threads and IC updates
    PlotArcListView         — /plots/arcs/      staff-only arc list with filters
    PlotArcDetailView       — /plots/arc/<pk>/  arc with IC updates + member plots
    PlotTagListView         — /plots/tags/      tag index

Authoring views:
    PlotCreateView          — /plots/new/
    PlotEditView            — /plots/<pk>/edit/
    PlotInviteView          — /plots/<pk>/invite/
    PlotOwnersView          — /plots/<pk>/owners/
    StoryThreadCreateView   — /plots/<pk>/threads/new/
    StoryThreadResolveView  — /plots/<pk>/threads/<number>/resolve/
    StoryThreadAnswerView   — /plots/<pk>/threads/<number>/answer/
    StoryThreadCarryView    — /plots/<pk>/threads/<number>/carry/
    StoryThreadActionView   — /plots/<pk>/threads/<number>/<action>/ (POST only)
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
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView
from evennia.objects.models import ObjectDB

from evennia_plots import threads as thread_services
from evennia_plots.authoring import AuthoringMixin
from evennia_plots.forms import (
    PlotArcCreateForm,
    PlotArcEditForm,
    PlotInviteForm,
    PlotOwnerForm,
    PlotTagCreateForm,
    PlotThreadCreateForm,
    PlotThreadEditForm,
    PlotUpdateEditForm,
    PlotUpdateForm,
    SealedAnswerForm,
    StoryThreadCarryForm,
    StoryThreadForm,
    StoryThreadResolveForm,
)
from evennia_plots.models import (
    PlotArc,
    PlotTag,
    PlotThread,
    PlotUpdate,
    PlotUpdateVersion,
    StoryThread,
)
from evennia_plots.permissions import can_manage_arc, get_character_id, is_staff_user
from evennia_plots.signals import arc_currency_changed, arc_type_changed


def _character(character_id):
    return ObjectDB.objects.filter(pk=character_id).first() if character_id else None


def _require_manager(request, plot, character_id):
    """Raise PermissionDenied unless the acting character owns *plot*, or is staff."""
    if is_staff_user(request):
        return
    if character_id and plot.owners.filter(character_id=character_id).exists():
        return
    raise PermissionDenied


def _with_open_thread_counts(queryset):
    """Annotate plots with ``open_thread_count`` and ``owner_led`` for list pages."""
    held_open = StoryThread.objects.filter(
        plot=OuterRef("pk"), status=StoryThread.Status.OPEN, is_held=True
    )
    return queryset.annotate(
        open_thread_count=Count(
            "story_threads",
            filter=Q(story_threads__status=StoryThread.Status.OPEN),
            distinct=True,
        ),
        owner_led=Exists(held_open),
    )


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
            .prefetch_related("tags", "owners")
            .order_by("-created_at")
        )
        tag = self.request.GET.get("tag", "").strip()
        if tag:
            qs = qs.filter(tags__name__icontains=tag).distinct()
        return _with_open_thread_counts(qs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Plots"
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
        context["page_title"] = f"Plot: {thread.name}"

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

        staff = is_staff_user(self.request)
        character_id = get_character_id(self.request.user)
        character = _character(character_id)
        manages = staff or thread.is_owner(character)
        story_threads = thread_services.visible_threads(thread, character)
        for story_thread in story_threads:
            story_thread.actions = thread_services.available_actions(story_thread, character)
            story_thread.leads = [
                i.character_name for i in story_thread.interests.all() if i.is_lead
            ]
            story_thread.interested_count = sum(
                1 for i in story_thread.interests.all() if not i.is_lead
            )
        live = (StoryThread.Status.OPEN, StoryThread.Status.REQUESTED)
        context["open_story_threads"] = sorted(
            (t for t in story_threads if t.status in live),
            key=lambda t: (t.status != StoryThread.Status.OPEN, not t.is_held, t.number),
        )
        context["finished_story_threads"] = [t for t in story_threads if t.status not in live]
        if thread_services.can_add_directly(thread, character):
            context["thread_add_mode"] = "add"
        elif thread_services.can_request(thread, character):
            context["thread_add_mode"] = "request"
        else:
            context["thread_add_mode"] = ""
        context["owners"] = thread.owners.all()
        context["is_owner_led"] = thread.is_owner_led
        context["can_manage"] = manages
        context["staff_log"] = list(reversed(thread.staff_log or []))[:10] if manages else []

        context["is_staff"] = staff
        context["character_id"] = character_id
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
        context["page_title"] = "Start a New Plot"
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
            thread_policy=form.cleaned_data.get("thread_policy") or None,
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotEditView(AuthoringMixin, FormView):
    """Edit an existing plot's name, description, privacy or thread policy.

    Permission: owners or staff.
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
        _require_manager(self.request, target, character_id)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_thread()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thread = self._get_thread()
        context["page_title"] = f"Edit Plot: {thread.name}"
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
            thread_policy=form.cleaned_data.get("thread_policy") or None,
        )
        return HttpResponseRedirect(reverse("evennia_plots:plot-detail", kwargs={"pk": thread.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PlotInviteView(AuthoringMixin, FormView):
    """Toggle invited characters on an invite-only plot.

    Permission: owners or staff. The form takes a character name string;
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
        _require_manager(self.request, target, character_id)

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
                css = "evennia-plots-diff-meta"
            elif line.startswith("@@"):
                css = "evennia-plots-diff-hunk"
            elif line.startswith("+"):
                css = "evennia-plots-diff-add"
            elif line.startswith("-"):
                css = "evennia-plots-diff-remove"
            else:
                css = "evennia-plots-diff-context"
            diff_lines.append((css, line))

        context["page_title"] = f"Diff v{version.version_number} — {thread.name}"
        context["thread"] = thread
        context["update"] = update
        context["version"] = version
        context["diff_lines"] = diff_lines
        context["no_diff"] = not diff_lines
        return context


# ---------------------------------------------------------------------------
# Owners and threads
# ---------------------------------------------------------------------------
# Private plots are not served on the web (see PlotDetailView), so neither are
# their owner and thread pages. Every rule lives in evennia_plots.threads; the
# views only translate ThreadError into a form error or a flash message.


def _web_plot(pk):
    return get_object_or_404(PlotThread.objects.exclude(privacy=PlotThread.Privacy.PRIVATE), pk=pk)


def _plot_threads_url(plot):
    return reverse("evennia_plots:plot-detail", kwargs={"pk": plot.pk}) + "#threads"


class _StoryThreadMixin:
    """Look up the plot and thread from the URL, as the acting character sees them."""

    def _get_plot(self):
        if not hasattr(self, "_plot"):
            self._plot = _web_plot(self.kwargs["pk"])
        return self._plot

    def _get_story_thread(self):
        if not hasattr(self, "_story_thread"):
            plot = self._get_plot()
            thread = get_object_or_404(StoryThread, plot=plot, number=self.kwargs["number"])
            character = _character(self.get_character())
            if thread not in thread_services.visible_threads(plot, character):
                raise Http404
            self._story_thread = thread
        return self._story_thread

    def get_permission_target(self):
        return self._get_story_thread()


class PlotOwnersView(AuthoringMixin, FormView):
    """Add or remove a plot's owners. Permission: owners or staff."""

    form_class = PlotOwnerForm
    template_name = "evennia_plots/plot_owners_form.html"

    def _get_plot(self):
        if not hasattr(self, "_plot"):
            self._plot = _web_plot(self.kwargs["pk"])
        return self._plot

    def get_permission_target(self):
        return self._get_plot()

    def check_permission(self, character_id, target):
        _require_manager(self.request, target, character_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plot = self._get_plot()
        context["page_title"] = f"Owners: {plot.name}"
        context["thread"] = plot
        context["owners"] = plot.owners.all()
        context["form_action"] = reverse("evennia_plots:plot-owners", kwargs={"pk": plot.pk})
        return context

    def form_valid(self, form):
        plot = self._get_plot()
        actor = _character(self.get_character())
        name = form.cleaned_data["character_name"].strip()
        target = ObjectDB.objects.filter(db_key__iexact=name).first()
        if target is None:
            form.add_error("character_name", f"No character named '{name}' found.")
            return self.form_invalid(form)
        try:
            if form.cleaned_data["action"] == PlotOwnerForm.ACTION_ADD:
                thread_services.add_owner(plot, actor, target)
            else:
                thread_services.remove_owner(plot, actor, target)
        except thread_services.ThreadError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse("evennia_plots:plot-owners", kwargs={"pk": plot.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class StoryThreadCreateView(AuthoringMixin, FormView):
    """Add a thread to a plot, or request one, as the plot's policy allows."""

    form_class = StoryThreadForm
    template_name = "evennia_plots/plot_thread_form.html"

    def _get_plot(self):
        if not hasattr(self, "_plot"):
            self._plot = _web_plot(self.kwargs["pk"])
        return self._plot

    def get_permission_target(self):
        return self._get_plot()

    def _mode(self):
        character = _character(self.get_character())
        plot = self._get_plot()
        if thread_services.can_add_directly(plot, character):
            return "add"
        if thread_services.can_request(plot, character):
            return "request"
        return ""

    def check_permission(self, character_id, target):
        if not self._mode():
            raise PermissionDenied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plot = self._get_plot()
        mode = self._mode()
        context["page_title"] = (
            f"Request a Thread: {plot.name}" if mode == "request" else f"Add a Thread: {plot.name}"
        )
        context["thread"] = plot
        context["mode"] = mode
        context["submit_label"] = "Send Request" if mode == "request" else "Add Thread"
        context["form_action"] = reverse("evennia_plots:plot-thread-create", kwargs={"pk": plot.pk})
        return context

    def form_valid(self, form):
        plot = self._get_plot()
        try:
            thread_services.add_thread(
                plot,
                _character(self.get_character()),
                form.cleaned_data["title"],
                form.cleaned_data.get("detail", ""),
            )
        except thread_services.ThreadError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(_plot_threads_url(plot))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class StoryThreadActionView(_StoryThreadMixin, AuthoringMixin, View):
    """POST-only one-step thread actions; the outcome is flashed on the plot page."""

    http_method_names = ["post"]  # noqa: RUF012
    ACTIONS = (
        "accept",
        "decline",
        "withdraw",
        "hold",
        "unhold",
        "lead",
        "interest",
        "drop",
        "reopen",
        "reveal",
    )

    def check_permission(self, character_id, target):
        """Each action checks its own rules in evennia_plots.threads."""

    def post(self, request, *args, **kwargs):
        action = kwargs["action"]
        if action not in self.ACTIONS:
            raise Http404
        actor = get_object_or_404(ObjectDB, pk=self.get_character())
        thread = self._get_story_thread()
        plot = thread.plot
        ref = thread.ref
        try:
            if action == "accept":
                thread_services.accept(thread, actor)
                note = f"Thread {ref} is open."
            elif action == "decline":
                thread_services.decline(thread, actor, request.POST.get("reason", ""))
                note = f"Declined thread request {ref}."
            elif action == "withdraw":
                thread_services.withdraw(thread, actor)
                note = f"Withdrew your request {ref}."
            elif action in ("hold", "unhold"):
                thread_services.set_held(thread, actor, action == "hold")
                note = f"Thread {ref} is held." if action == "hold" else f"{ref} is no longer held."
            elif action == "lead":
                leading = thread_services.toggle_lead(thread, actor)
                note = f"You're leading {ref}." if leading else f"You're no longer leading {ref}."
            elif action == "interest":
                interested = thread_services.toggle_interest(thread, actor)
                note = (
                    f"Marked your interest in {ref}."
                    if interested
                    else f"Removed your interest in {ref}."
                )
            elif action == "drop":
                thread_services.drop(thread, actor)
                note = f"Dropped {ref}."
            elif action == "reopen":
                thread_services.reopen(thread, actor)
                note = f"Reopened {ref}."
            else:
                thread_services.reveal(thread, actor)
                note = f"Revealed the planned answer to {ref}."
            messages.success(request, note, fail_silently=True)
        except thread_services.ThreadError as exc:
            messages.error(request, str(exc), fail_silently=True)
        return HttpResponseRedirect(_plot_threads_url(plot))


class StoryThreadResolveView(_StoryThreadMixin, AuthoringMixin, FormView):
    """Resolve a thread with a summary; owners may reveal its sealed answer."""

    form_class = StoryThreadResolveForm
    template_name = "evennia_plots/plot_thread_resolve_form.html"

    def check_permission(self, character_id, target):
        if not thread_services.can_resolve(target, _character(character_id)):
            raise PermissionDenied

    def _manages(self):
        return self._get_story_thread().plot.can_manage(_character(self.get_character()))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        story_thread = self._get_story_thread()
        manages = self._manages()
        context["page_title"] = f"Resolve {story_thread.ref}: {story_thread.title}"
        context["thread"] = story_thread.plot
        context["story_thread"] = story_thread
        context["offer_reveal"] = manages and story_thread.answer_is_sealed
        context["form_action"] = reverse(
            "evennia_plots:plot-thread-resolve",
            kwargs={"pk": story_thread.plot.pk, "number": story_thread.number},
        )
        return context

    def form_valid(self, form):
        story_thread = self._get_story_thread()
        try:
            thread_services.resolve(
                story_thread,
                _character(self.get_character()),
                form.cleaned_data["summary"],
                reveal_answer=bool(form.cleaned_data.get("reveal")) and self._manages(),
            )
        except thread_services.ThreadError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(_plot_threads_url(story_thread.plot))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class StoryThreadAnswerView(_StoryThreadMixin, AuthoringMixin, FormView):
    """Read a thread's sealed answer and its history; owners also write it.

    Owners and staff always see it. Once revealed, anyone who can see the plot
    may read it. Everyone else gets a 404, never a hint that an answer exists.
    """

    form_class = SealedAnswerForm
    template_name = "evennia_plots/plot_thread_answer.html"

    def _manages(self):
        return self._get_story_thread().plot.can_manage(_character(self.get_character()))

    def _can_edit(self):
        return self._manages() and self._get_story_thread().status == StoryThread.Status.OPEN

    def check_permission(self, character_id, target):
        if self._can_edit():
            return
        if not thread_services.can_read_answer(target, _character(character_id)):
            raise Http404

    def get_initial(self):
        return {"answer": self._get_story_thread().sealed_answer}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        story_thread = self._get_story_thread()
        context["page_title"] = f"Answer to {story_thread.ref}: {story_thread.title}"
        context["thread"] = story_thread.plot
        context["story_thread"] = story_thread
        context["can_edit"] = self._can_edit()
        context["versions"] = story_thread.answer_versions.order_by("-version_number")
        context["form_action"] = reverse(
            "evennia_plots:plot-thread-answer",
            kwargs={"pk": story_thread.plot.pk, "number": story_thread.number},
        )
        return context

    def form_valid(self, form):
        story_thread = self._get_story_thread()
        if not self._can_edit():
            raise PermissionDenied
        try:
            thread_services.seal(
                story_thread, _character(self.get_character()), form.cleaned_data["answer"]
            )
        except thread_services.ThreadError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(
            reverse(
                "evennia_plots:plot-thread-answer",
                kwargs={"pk": story_thread.plot.pk, "number": story_thread.number},
            )
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class StoryThreadCarryView(_StoryThreadMixin, AuthoringMixin, FormView):
    """Carry a loose end into a sequel plot the actor also runs."""

    form_class = StoryThreadCarryForm
    template_name = "evennia_plots/plot_thread_carry_form.html"

    def _targets(self):
        return thread_services.carry_targets(
            self._get_story_thread(), _character(self.get_character())
        )

    def check_permission(self, character_id, target):
        if target.status != StoryThread.Status.LOOSE_END:
            raise PermissionDenied
        _require_manager(self.request, target.plot, character_id)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["targets"] = self._targets()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        story_thread = self._get_story_thread()
        context["page_title"] = f"Carry {story_thread.ref}: {story_thread.title}"
        context["thread"] = story_thread.plot
        context["story_thread"] = story_thread
        context["targets"] = self._targets()
        context["form_action"] = reverse(
            "evennia_plots:plot-thread-carry",
            kwargs={"pk": story_thread.plot.pk, "number": story_thread.number},
        )
        return context

    def form_valid(self, form):
        story_thread = self._get_story_thread()
        target = get_object_or_404(PlotThread, pk=form.cleaned_data["target"])
        try:
            thread_services.carry(story_thread, _character(self.get_character()), target)
        except thread_services.ThreadError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(_plot_threads_url(target))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


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
