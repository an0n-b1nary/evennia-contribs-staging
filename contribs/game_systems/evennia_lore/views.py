# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Website views for evennia_lore (requires [web] extra).

Views:
    LoreListView           — /lore/       paginated PUBLISHED entries + filters
    LoreDetailView         — /lore/<pk>/  full body or stub based on access
    LoreCompendiumView     — /lore/mine/  character's acquired entries
    LoreApprovalQueueView  — /lore/queue/ SUBMITTED entries (staff only)
    LoreCreateView         — /lore/new/   submit new entry
    LoreEditView           — /lore/<pk>/edit/   edit body/title/summary/privacy
    LoreVersionHistoryView — /lore/<pk>/history/  list LoreVersion snapshots
    LoreVersionDiffView    — /lore/<pk>/diff/<v>/  unified diff
    LoreLeanView           — /lore/lean/  set/clear +investigate lean
    LoreApproveView        — /lore/<pk>/approve/  POST; staff only
    LoreRejectView         — /lore/<pk>/reject/   POST; staff only

Wire into your URL config::

    from django.urls import include, path
    urlpatterns += [path("lore/", include("evennia_lore.urls"))]
"""

import difflib

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView, TemplateView, View
from evennia.objects.models import ObjectDB

from evennia_lore.authoring import AuthoringMixin
from evennia_lore.forms import LoreEntryCreateForm, LoreEntryEditForm, LoreLeanForm
from evennia_lore.models import (
    LoreAcquisition,
    LoreEntry,
    LoreRegionLink,
    LoreTag,
    LoreVersion,
)
from evennia_lore.permissions import get_character_id, is_staff_user


class LoreListView(ListView):
    """Paginated list of PUBLISHED lore entries with tag/theme/region/search filters."""

    model = LoreEntry
    template_name = "evennia_lore/lore_list.html"
    context_object_name = "entries"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            LoreEntry.objects.filter(
                status=LoreEntry.Status.PUBLISHED,
                is_archived=False,
            )
            .prefetch_related("tags")
            .order_by("-created_at")
        )

        tag = self.request.GET.get("tag", "").strip()
        if tag:
            qs = qs.filter(tags__name__icontains=tag).distinct()

        theme = self.request.GET.get("theme", "").strip()
        if theme:
            qs = qs.filter(tags__name__icontains=theme, tags__is_major=True).distinct()

        region = self.request.GET.get("region", "").strip()
        if region:
            from django.apps import apps as django_apps
            from django.conf import settings

            try:
                regions_label = getattr(settings, "LORE_REGIONS_APP_LABEL", "evennia_regions")
                Region = django_apps.get_model(regions_label, "Region")
                region_ids = Region.objects.filter(name__icontains=region).values_list(
                    "pk", flat=True
                )
                entry_ids = LoreRegionLink.objects.filter(region_id__in=region_ids).values_list(
                    "entry_id", flat=True
                )
                qs = qs.filter(pk__in=entry_ids).distinct()
            except Exception:
                pass

        search = self.request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(body__icontains=search)).distinct()

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Lore Compendium"
        context["tag_filter"] = self.request.GET.get("tag", "")
        context["theme_filter"] = self.request.GET.get("theme", "")
        context["region_filter"] = self.request.GET.get("region", "")
        context["search_filter"] = self.request.GET.get("search", "")
        context["all_major_tags"] = LoreTag.objects.filter(is_major=True).order_by("name")
        context["is_staff"] = is_staff_user(self.request)
        character_id = get_character_id(self.request.user)
        context["character_id"] = character_id
        if character_id:
            context["acquired_pks"] = set(
                LoreAcquisition.objects.filter(character_id=character_id).values_list(
                    "entry_id", flat=True
                )
            )
        else:
            context["acquired_pks"] = set()
        return context


class LoreDetailView(DetailView):
    """Detail view for a single lore entry."""

    model = LoreEntry
    template_name = "evennia_lore/lore_detail.html"
    context_object_name = "entry"

    def get_queryset(self):
        if is_staff_user(self.request):
            return LoreEntry.objects.all()
        return LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED, is_archived=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self.object
        context["page_title"] = entry.title
        context["is_staff"] = is_staff_user(self.request)
        character_id = get_character_id(self.request.user)
        context["character_id"] = character_id

        character = None
        if character_id:
            character = ObjectDB.objects.filter(pk=character_id).first()
        context["is_accessible"] = is_staff_user(self.request) or entry.is_accessible_to(character)
        context["has_acquired"] = (
            LoreAcquisition.objects.filter(entry=entry, character_id=character_id).exists()
            if character_id
            else False
        )

        # Resolve scene/plot soft-refs into real objects for the template.
        from django.apps import apps as django_apps
        from django.conf import settings

        scene_ids = list(
            entry.scene_links.order_by("created_at").values_list("scene_id", flat=True)
        )
        linked_scenes = []
        try:
            scenes_label = getattr(settings, "LORE_SCENES_APP_LABEL", "evennia_scenes")
            Scene = django_apps.get_model(scenes_label, "Scene")
            scenes_by_id = {s.pk: s for s in Scene.all_objects.filter(pk__in=scene_ids)}
            linked_scenes = [scenes_by_id[sid] for sid in scene_ids if sid in scenes_by_id]
        except Exception:
            pass
        context["linked_scenes"] = linked_scenes

        thread_ids = list(
            entry.plot_links.order_by("created_at").values_list("thread_id", flat=True)
        )
        linked_plots = []
        try:
            plots_label = getattr(settings, "LORE_PLOTS_APP_LABEL", "evennia_plots")
            PlotThread = django_apps.get_model(plots_label, "PlotThread")
            threads_by_id = {t.pk: t for t in PlotThread.objects.filter(pk__in=thread_ids)}
            linked_plots = [threads_by_id[tid] for tid in thread_ids if tid in threads_by_id]
        except Exception:
            pass
        context["linked_plots"] = linked_plots

        region_ids = LoreRegionLink.objects.filter(entry=entry).values_list("region_id", flat=True)
        region_list = []
        try:
            regions_label = getattr(settings, "LORE_REGIONS_APP_LABEL", "evennia_regions")
            Region = django_apps.get_model(regions_label, "Region")
            region_list = list(Region.objects.filter(pk__in=list(region_ids)).order_by("name"))
        except Exception:
            pass
        context["region_list"] = region_list
        context["versions"] = entry.versions.order_by("-version_number")[:5]
        return context


class LoreCompendiumView(LoginRequiredMixin, ListView):
    """The requesting character's acquired lore entries (/lore/mine/)."""

    template_name = "evennia_lore/lore_compendium.html"
    context_object_name = "acquisitions"
    paginate_by = 20
    login_url = "/accounts/login/"

    def get_queryset(self):
        character_id = get_character_id(self.request.user)
        if not character_id:
            return LoreAcquisition.objects.none()
        return (
            LoreAcquisition.objects.filter(character_id=character_id)
            .select_related("entry")
            .order_by("-acquired_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "My Lore Compendium"
        context["character_id"] = get_character_id(self.request.user)
        return context


class LoreApprovalQueueView(LoginRequiredMixin, ListView):
    """SUBMITTED entries awaiting staff review. Builder+ only."""

    template_name = "evennia_lore/lore_queue.html"
    context_object_name = "entries"
    login_url = "/accounts/login/"

    def get_queryset(self):
        if not is_staff_user(self.request):
            raise PermissionDenied
        return LoreEntry.objects.filter(status=LoreEntry.Status.SUBMITTED).order_by("created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Lore Approval Queue"
        context["is_staff"] = True
        return context


class LoreCreateView(AuthoringMixin, FormView):
    """Submit a new lore entry. Any logged-in puppeted character may create."""

    form_class = LoreEntryCreateForm
    template_name = "evennia_lore/lore_form.html"

    def check_permission(self, character_id, target):
        pass

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Submit Lore Entry"
        context["form_action"] = reverse("lore-create")
        context["is_edit"] = False
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        entry = LoreEntry.create_entry(
            title=form.cleaned_data["title"],
            author=character,
            body=form.cleaned_data.get("body", ""),
            summary=form.cleaned_data.get("summary", ""),
            privacy=form.cleaned_data.get("privacy", LoreEntry.Privacy.PUBLIC),
        )
        return HttpResponseRedirect(reverse("lore-detail", kwargs={"pk": entry.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class LoreEditView(AuthoringMixin, FormView):
    """Edit an existing lore entry. Permission: author or staff."""

    form_class = LoreEntryEditForm
    template_name = "evennia_lore/lore_form.html"

    def _get_entry(self):
        if not hasattr(self, "_entry"):
            self._entry = get_object_or_404(LoreEntry, pk=self.kwargs["pk"])
        return self._entry

    def get_permission_target(self):
        return self._get_entry()

    def check_permission(self, character_id, target):
        entry = target
        if is_staff_user(self.request):
            return
        if entry.author_id and entry.author_id == character_id:
            return
        raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_entry()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._get_entry()
        context["page_title"] = f"Edit: {entry.title}"
        context["entry"] = entry
        context["form_action"] = reverse("lore-edit", kwargs={"pk": entry.pk})
        context["is_edit"] = True
        return context

    def form_valid(self, form):
        from django.utils import timezone

        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        entry = self._get_entry()
        old_body = LoreEntry.objects.values_list("body", flat=True).get(pk=entry.pk)
        LoreVersion.create_version(parent=entry, content=old_body, editor=character)
        entry.body = form.cleaned_data["body"]
        entry.title = form.cleaned_data["title"]
        entry.summary = form.cleaned_data.get("summary", entry.summary)
        entry.privacy = form.cleaned_data.get("privacy", entry.privacy)
        entry.updated_at = timezone.now()
        entry.save(update_fields=["body", "title", "summary", "privacy", "updated_at"])
        return HttpResponseRedirect(reverse("lore-detail", kwargs={"pk": entry.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class LoreVersionHistoryView(TemplateView):
    """List all version snapshots for a lore entry."""

    template_name = "evennia_lore/lore_history.html"

    def _get_entry(self):
        if not hasattr(self, "_entry"):
            self._entry = get_object_or_404(LoreEntry, pk=self.kwargs["pk"])
        return self._entry

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._get_entry()
        context["page_title"] = f"Edit History — {entry.title}"
        context["entry"] = entry
        context["versions"] = LoreVersion.objects.filter(parent=entry).order_by("-version_number")
        return context


class LoreVersionDiffView(TemplateView):
    """Unified diff between a LoreVersion snapshot and the current body."""

    template_name = "evennia_lore/lore_diff.html"

    def _get_entry(self):
        if not hasattr(self, "_entry"):
            self._entry = get_object_or_404(LoreEntry, pk=self.kwargs["pk"])
        return self._entry

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self._get_entry()
        version = get_object_or_404(
            LoreVersion,
            parent=entry,
            version_number=self.kwargs["version_number"],
        )

        old_lines = version.content.splitlines(keepends=True)
        new_lines = entry.body.splitlines(keepends=True)
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
                diff_lines.append(("header", line))
            elif line.startswith("@@"):
                diff_lines.append(("hunk", line))
            elif line.startswith("+"):
                diff_lines.append(("add", line))
            elif line.startswith("-"):
                diff_lines.append(("remove", line))
            else:
                diff_lines.append(("context", line))

        context["page_title"] = f"Diff v{version.version_number} — {entry.title}"
        context["entry"] = entry
        context["version"] = version
        context["diff_lines"] = diff_lines
        return context


class LoreLeanView(AuthoringMixin, FormView):
    """Set or clear the +investigate lean from the web (/lore/lean/)."""

    form_class = LoreLeanForm
    template_name = "evennia_lore/lore_lean_form.html"

    def check_permission(self, character_id, target):
        pass

    def get_initial(self):
        character_id = self.get_character()
        character = ObjectDB.objects.filter(pk=character_id).first()
        if character is None:
            return {}
        return {
            "lean_type": getattr(character, "lore_lean_type", None) or "",
            "lean_value": getattr(character, "lore_lean_value", None) or "",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Set Investigation Lean"
        context["form_action"] = reverse("lore-lean")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        lean_type = form.cleaned_data.get("lean_type") or None
        lean_value = form.cleaned_data.get("lean_value") or None
        character.lore_lean_type = lean_type
        character.lore_lean_value = lean_value
        return HttpResponseRedirect(reverse("lore-lean"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class LoreApproveView(LoginRequiredMixin, View):
    """POST-only: approve a SUBMITTED entry. Staff only."""

    login_url = "/accounts/login/"

    def post(self, request, pk):
        if not is_staff_user(request):
            raise PermissionDenied
        entry = get_object_or_404(LoreEntry, pk=pk)
        character_id = get_character_id(request.user)
        character = ObjectDB.objects.filter(pk=character_id).first() if character_id else None
        entry.publish(reviewed_by=character)
        return HttpResponseRedirect(reverse("lore-detail", kwargs={"pk": entry.pk}))


class LoreRejectView(LoginRequiredMixin, View):
    """POST-only: reject a SUBMITTED entry. Staff only."""

    login_url = "/accounts/login/"

    def post(self, request, pk):
        if not is_staff_user(request):
            raise PermissionDenied
        entry = get_object_or_404(LoreEntry, pk=pk)
        character_id = get_character_id(request.user)
        character = ObjectDB.objects.filter(pk=character_id).first() if character_id else None
        entry.reject(reviewed_by=character, editor=character)
        return HttpResponseRedirect(reverse("lore-queue"))
