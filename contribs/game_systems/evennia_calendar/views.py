# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for evennia_calendar. Requires [web] extra.

Read-only public views:
  /calendar/                       — CalendarMonthView
  /calendar/list/                  — CalendarListView
  /calendar/<pk>/                  — CalendarEventDetailView
  /calendar/cluster/<pk>/          — ClusterDetailView (+ ranked RSVP POST)

Authoring views (login + puppet required):
  /calendar/new/                   — EventCreateView
  /calendar/<pk>/edit/             — EventEditView
  /calendar/<pk>/cancel/           — EventCancelView
  /calendar/<pk>/invite/           — EventInviteView
  /calendar/<pk>/tags/             — EventTagView
  /calendar/<pk>/exclusions/       — ExclusionManageView
  /calendar/cluster/new/           — ClusterCreateView
  /calendar/cluster/<pk>/edit/     — ClusterEditView
  /calendar/cluster/<pk>/members/  — ClusterMembershipView

Timezone display: all times are stored UTC. JavaScript renders them in the
visitor's local timezone via ``new Date(isoString).toLocaleString()``.
"""

import calendar as _cal
import contextlib
import datetime

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView, TemplateView
from evennia.objects.models import ObjectDB

from evennia_calendar.authoring import CalendarAuthoringMixin
from evennia_calendar.forms import (
    CalendarEventEditForm,
    CalendarEventForm,
    ClusterRSVPForm,
    EventClusterForm,
    EventClusterMembershipForm,
    EventInviteForm,
    EventTagCreateForm,
    EventTagForm,
    ExclusionForm,
)
from evennia_calendar.models import (
    RSVP,
    CalendarEvent,
    ClusterRSVP,
    ClusterRSVPPreference,
    EventCluster,
    EventExclusion,
    EventTag,
)
from evennia_calendar.permissions import get_character_id, is_staff_user


class CalendarMonthView(TemplateView):
    """Month grid view. Default landing page for /calendar/."""

    template_name = "evennia_calendar/calendar_month.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.now()
        try:
            year = int(self.request.GET.get("year", now.year))
            month = int(self.request.GET.get("month", now.month))
        except ValueError:
            year, month = now.year, now.month
        year = max(2020, min(year, 2040))
        month = max(1, min(month, 12))

        cal = _cal.monthcalendar(year, month)
        month_start = datetime.datetime(year, month, 1, tzinfo=datetime.UTC)
        if month == 12:
            month_end = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.UTC)
        else:
            month_end = datetime.datetime(year, month + 1, 1, tzinfo=datetime.UTC)

        events = (
            CalendarEvent.objects.filter(
                is_cancelled=False,
                scheduled_time__gte=month_start,
                scheduled_time__lt=month_end,
            )
            .prefetch_related("tags", "cluster")
            .order_by("scheduled_time")
        )

        day_events = {}
        for ev in events:
            day = ev.scheduled_time.day
            day_events.setdefault(day, []).append(ev)

        cal_weeks_with_events = [[(day, day_events.get(day, [])) for day in week] for week in cal]

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        context.update(
            {
                "page_title": f"Event Calendar — {_cal.month_name[month]} {year}",
                "year": year,
                "month": month,
                "month_name": _cal.month_name[month],
                "cal_weeks_with_events": cal_weeks_with_events,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "today": now.day if (now.year == year and now.month == month) else None,
            }
        )
        return context


class CalendarListView(ListView):
    """Chronological list of upcoming (and optionally past) events."""

    model = CalendarEvent
    template_name = "evennia_calendar/calendar_list.html"
    context_object_name = "events"
    paginate_by = 25

    def get_queryset(self):
        qs = CalendarEvent.objects.filter(is_cancelled=False).prefetch_related("tags", "cluster")
        if self.request.GET.get("past"):
            qs = qs.filter(scheduled_time__lt=timezone.now()).order_by("-scheduled_time")
        else:
            qs = qs.filter(scheduled_time__gte=timezone.now()).order_by("scheduled_time")
        emphasis = self.request.GET.get("emphasis")
        if emphasis:
            qs = qs.filter(emphasis=emphasis)
        tag = self.request.GET.get("tag")
        if tag:
            qs = qs.filter(tags__name__iexact=tag).distinct()
        if self.request.GET.get("staff"):
            qs = qs.filter(is_staff_event=True)
        if self.request.GET.get("clustered"):
            qs = qs.filter(cluster__isnull=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Event Calendar — List"
        context["tags"] = EventTag.objects.all()
        context["emphasis_choices"] = CalendarEvent.Emphasis.choices
        context["filters"] = {
            "past": self.request.GET.get("past", ""),
            "emphasis": self.request.GET.get("emphasis", ""),
            "tag": self.request.GET.get("tag", ""),
            "staff": self.request.GET.get("staff", ""),
            "clustered": self.request.GET.get("clustered", ""),
        }
        context["is_staff"] = is_staff_user(self.request)
        return context


class CalendarEventDetailView(DetailView):
    """Event detail page showing description, RSVP roster, and cluster context."""

    model = CalendarEvent
    template_name = "evennia_calendar/calendar_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        return CalendarEvent.objects.filter(is_cancelled=False).prefetch_related(
            "tags", "cluster", "rsvps"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context["page_title"] = f"Event: {event.title}"
        rsvps = event.rsvps.exclude(status=RSVP.Status.RELEASED).order_by("status", "created_at")
        context["rsvps"] = rsvps
        if event.is_clustered:
            context["cluster_siblings"] = event.cluster.events.exclude(pk=event.pk).filter(
                is_cancelled=False
            )
        context["is_staff"] = is_staff_user(self.request)
        context["character_id"] = get_character_id(self.request.user)
        return context


class ClusterDetailView(TemplateView):
    """
    Cluster detail page with ranked-choice RSVP form.

    GET:  Display cluster metadata, member events, and ranked-choice form.
    POST: Submit or replace ranked preferences (logged-in puppeted characters).
          Validation errors are rendered in-place; success uses PRG.
    """

    template_name = "evennia_calendar/calendar_cluster.html"

    def _get_cluster(self):
        return get_object_or_404(EventCluster, pk=self.kwargs["pk"])

    def _get_active_character(self, request):
        """Return the puppeted Character object for the current session, or None."""
        if not request.user.is_authenticated:
            return None
        account = getattr(request.user, "account", None) or request.user
        puppets = account.get_all_puppets() if hasattr(account, "get_all_puppets") else []
        return puppets[0] if puppets else None

    def get(self, request, *args, **kwargs):
        cluster = self._get_cluster()
        character = self._get_active_character(request)

        existing_crsvp = None
        existing_prefs = []
        if character:
            try:
                existing_crsvp = ClusterRSVP.objects.get(cluster=cluster, character=character)
                existing_prefs = list(existing_crsvp.get_ordered_preferences())
            except ClusterRSVP.DoesNotExist:
                pass

        member_events = cluster.events.filter(is_cancelled=False).order_by("scheduled_time")
        initial_ids = [p.event_id for p in existing_prefs]
        form = ClusterRSVPForm(
            cluster=cluster,
            character_id=character.pk if character else None,
            initial={"preferences": initial_ids},
        )
        context = self._build_context(
            cluster, character, existing_crsvp, existing_prefs, member_events, form
        )
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        cluster = self._get_cluster()
        character = self._get_active_character(request)
        member_events = cluster.events.filter(is_cancelled=False).order_by("scheduled_time")

        if not character:
            form = ClusterRSVPForm(cluster=cluster, character_id=None)
            form.add_error(None, "You must be logged in with an active character to RSVP.")
            context = self._build_context(cluster, character, None, [], member_events, form)
            return self.render_to_response(context)

        form = ClusterRSVPForm(
            request.POST,
            cluster=cluster,
            character_id=character.pk,
        )

        if not form.is_valid():
            existing_crsvp = None
            existing_prefs = []
            try:
                existing_crsvp = ClusterRSVP.objects.get(cluster=cluster, character=character)
                existing_prefs = list(existing_crsvp.get_ordered_preferences())
            except ClusterRSVP.DoesNotExist:
                pass
            context = self._build_context(
                cluster, character, existing_crsvp, existing_prefs, member_events, form
            )
            return self.render_to_response(context)

        ranked_ids = form.cleaned_data["preferences"]
        events = []
        for pk in ranked_ids:
            with contextlib.suppress(CalendarEvent.DoesNotExist):
                events.append(CalendarEvent.objects.get(pk=pk, cluster=cluster, is_cancelled=False))

        crsvp, _created = ClusterRSVP.objects.get_or_create(
            cluster=cluster,
            character=character,
            defaults={"character_name": character.key},
        )
        crsvp.preferences.all().delete()
        for rank, ev in enumerate(events, start=1):
            ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=ev, rank=rank)

        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-cluster-detail", kwargs={"pk": cluster.pk})
            + "?success=1"
        )

    def _build_context(
        self, cluster, character, existing_crsvp, existing_prefs, member_events, form
    ):
        seated_event = None
        if existing_crsvp and existing_crsvp.status == ClusterRSVP.Status.SEATED:
            concrete = existing_crsvp.concrete_rsvps.first()
            if concrete:
                seated_event = concrete.event

        rsvp_counts = {}
        for ev in member_events:
            rsvp_counts[ev.pk] = ev.rsvps.exclude(status=RSVP.Status.RELEASED).count()

        existing_ranked_ids = [p.event_id for p in existing_prefs]
        success = self.request.GET.get("success")

        if form.is_bound:
            checked_event_ids = set()
            raw = (
                form.data.getlist("preferences")
                if hasattr(form.data, "getlist")
                else form.data.get("preferences", [])
            )
            for val in raw:
                with contextlib.suppress(ValueError, TypeError):
                    checked_event_ids.add(int(val))
        else:
            checked_event_ids = set(existing_ranked_ids)

        return {
            "page_title": f"Cluster: {cluster.title}",
            "cluster": cluster,
            "member_events": member_events,
            "character": character,
            "existing_crsvp": existing_crsvp,
            "existing_prefs": existing_prefs,
            "existing_ranked_ids": existing_ranked_ids,
            "seated_event": seated_event,
            "rsvp_counts": rsvp_counts,
            "form": form,
            "checked_event_ids": checked_event_ids,
            "success": bool(success),
        }


# ---------------------------------------------------------------------------
# Authoring views
# ---------------------------------------------------------------------------


def _event_or_404(pk):
    return get_object_or_404(CalendarEvent, pk=pk, is_cancelled=False)


def _cluster_or_404(pk):
    return get_object_or_404(EventCluster, pk=pk)


def _check_event_permission(request, character_id, event):
    """Raise PermissionDenied if character may not author this event."""
    if is_staff_user(request):
        return
    if event.creator_id and event.creator_id == character_id:
        return
    raise PermissionDenied


def _check_cluster_permission(request, character_id, cluster):
    """Raise PermissionDenied if character may not author this cluster."""
    if is_staff_user(request):
        return
    if cluster.creator_id and cluster.creator_id == character_id:
        return
    raise PermissionDenied


class EventCreateView(CalendarAuthoringMixin, FormView):
    """Create a new CalendarEvent. Any logged-in puppeted character may create."""

    form_class = CalendarEventForm
    template_name = "evennia_calendar/event_form.html"

    def check_permission(self, character_id, target):
        pass  # any puppet holder can create

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_staff"] = is_staff_user(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create New Event"
        context["form_action"] = reverse("evennia_calendar:calendar-event-create")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        data = form.cleaned_data
        event = CalendarEvent.create_event(
            creator=character,
            title=data["title"],
            scheduled_time=data["scheduled_time"],
            description=data.get("description", ""),
            emphasis=data.get("emphasis", CalendarEvent.Emphasis.FREEFORM),
            participant_cap=data.get("participant_cap"),
            is_staff_event=data.get("is_staff_event", False),
        )
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-event-detail", kwargs={"pk": event.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class EventEditView(CalendarAuthoringMixin, FormView):
    """Edit an existing CalendarEvent. Permission: creator or staff."""

    form_class = CalendarEventEditForm
    template_name = "evennia_calendar/event_form.html"

    def _get_event(self):
        if not hasattr(self, "_event"):
            self._event = _event_or_404(self.kwargs["pk"])
        return self._event

    def get_permission_target(self):
        return self._get_event()

    def check_permission(self, character_id, target):
        _check_event_permission(self.request, character_id, target)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_event()
        kwargs["is_staff"] = is_staff_user(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self._get_event()
        context["page_title"] = f"Edit Event: {event.title}"
        context["event"] = event
        context["form_action"] = reverse(
            "evennia_calendar:calendar-event-edit", kwargs={"pk": event.pk}
        )
        return context

    def form_valid(self, form):
        event = self._get_event()
        data = form.cleaned_data
        event.title = data["title"]
        event.description = data.get("description", "")
        event.scheduled_time = data["scheduled_time"]
        event.participant_cap = data.get("participant_cap")
        event.emphasis = data.get("emphasis", event.emphasis)
        if is_staff_user(self.request) and "is_staff_event" in data:
            event.is_staff_event = data["is_staff_event"]
        event.save()
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-event-detail", kwargs={"pk": event.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class EventCancelView(CalendarAuthoringMixin, TemplateView):
    """GET: confirmation page. POST: soft-cancel the event. Creator or staff."""

    template_name = "evennia_calendar/event_cancel.html"

    def _get_event(self):
        if not hasattr(self, "_event"):
            self._event = _event_or_404(self.kwargs["pk"])
        return self._event

    def get_permission_target(self):
        return self._get_event()

    def check_permission(self, character_id, target):
        _check_event_permission(self.request, character_id, target)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self._get_event()
        context["page_title"] = f"Cancel Event: {event.title}"
        context["event"] = event
        return context

    def post(self, request, *args, **kwargs):
        event = self._get_event()
        event.cancel()
        return HttpResponseRedirect(reverse("evennia_calendar:calendar-list"))


class EventInviteView(CalendarAuthoringMixin, FormView):
    """Invite a character to a non-staff event. Blocked on staff events."""

    form_class = EventInviteForm
    template_name = "evennia_calendar/event_invite_form.html"

    def _get_event(self):
        if not hasattr(self, "_event"):
            self._event = _event_or_404(self.kwargs["pk"])
        return self._event

    def get_permission_target(self):
        return self._get_event()

    def check_permission(self, character_id, target):
        event = target
        if event.is_staff_event:
            raise PermissionDenied(
                "Pre-inviting participants is disabled on staff events "
                "(anti-favouritism enforcement)."
            )
        _check_event_permission(self.request, character_id, event)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self._get_event()
        context["page_title"] = f"Invite to: {event.title}"
        context["event"] = event
        context["invited_rsvps"] = event.rsvps.filter(status=RSVP.Status.INVITED).order_by(
            "character_name"
        )
        context["form_action"] = reverse(
            "evennia_calendar:calendar-event-invite", kwargs={"pk": event.pk}
        )
        return context

    def form_valid(self, form):
        event = self._get_event()
        char_name = form.cleaned_data["character_name"].strip()
        target_char = ObjectDB.objects.filter(db_key__iexact=char_name).first()
        if target_char is None:
            form.add_error("character_name", f"No character named '{char_name}' found.")
            return self.form_invalid(form)
        RSVP.objects.get_or_create(
            event=event,
            character=target_char,
            defaults={
                "character_name": target_char.key,
                "status": RSVP.Status.INVITED,
            },
        )
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-event-invite", kwargs={"pk": event.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class EventTagCreateView(CalendarAuthoringMixin, FormView):
    """Create a new canonical EventTag. Builder+ only."""

    form_class = EventTagCreateForm
    template_name = "evennia_calendar/event_tag_create_form.html"

    def check_permission(self, character_id, target):
        if not is_staff_user(self.request):
            raise PermissionDenied("Only staff may create canonical tags.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Event Tag"
        context["existing_tags"] = EventTag.objects.order_by("name")
        context["form_action"] = reverse("evennia_calendar:calendar-tag-create")
        return context

    def form_valid(self, form):
        form.save()
        return HttpResponseRedirect(reverse("evennia_calendar:calendar-tag-create"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class EventTagView(CalendarAuthoringMixin, FormView):
    """Add or remove a thematic tag on a CalendarEvent. Creator or staff."""

    form_class = EventTagForm
    template_name = "evennia_calendar/event_tag_form.html"

    def _get_event(self):
        if not hasattr(self, "_event"):
            self._event = _event_or_404(self.kwargs["pk"])
        return self._event

    def get_permission_target(self):
        return self._get_event()

    def check_permission(self, character_id, target):
        _check_event_permission(self.request, character_id, target)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self._get_event()
        context["page_title"] = f"Manage Tags: {event.title}"
        context["event"] = event
        context["current_tags"] = event.tags.order_by("name")
        context["available_tags"] = EventTag.objects.order_by("name")
        context["form_action"] = reverse(
            "evennia_calendar:calendar-event-tags", kwargs={"pk": event.pk}
        )
        return context

    def form_valid(self, form):
        event = self._get_event()
        tag_name = form.cleaned_data["tag_name"].strip()
        action = form.cleaned_data["action"]
        tag = EventTag.objects.filter(name__iexact=tag_name).first()
        if tag is None:
            form.add_error("tag_name", f"No tag named '{tag_name}' exists.")
            return self.form_invalid(form)
        if action == "add":
            event.tags.add(tag)
        else:
            event.tags.remove(tag)
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-event-tags", kwargs={"pk": event.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ExclusionManageView(CalendarAuthoringMixin, FormView):
    """Add or remove mutual-exclusion pairs for an event. Creator or staff."""

    form_class = ExclusionForm
    template_name = "evennia_calendar/exclusion_form.html"

    def _get_event(self):
        if not hasattr(self, "_event"):
            self._event = _event_or_404(self.kwargs["pk"])
        return self._event

    def get_permission_target(self):
        return self._get_event()

    def check_permission(self, character_id, target):
        _check_event_permission(self.request, character_id, target)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self._get_event()
        context["page_title"] = f"Manage Exclusions: {event.title}"
        context["event"] = event
        context["excluded_events"] = EventExclusion.get_exclusions_for(event)
        context["form_action"] = reverse(
            "evennia_calendar:calendar-event-exclusions", kwargs={"pk": event.pk}
        )
        return context

    def form_valid(self, form):
        event = self._get_event()
        other_id = form.cleaned_data["other_event_id"]
        action = form.cleaned_data["action"]

        if other_id == event.pk:
            form.add_error("other_event_id", "An event cannot exclude itself.")
            return self.form_invalid(form)

        other_event = CalendarEvent.objects.filter(pk=other_id, is_cancelled=False).first()
        if other_event is None:
            form.add_error("other_event_id", f"No active event with ID {other_id} found.")
            return self.form_invalid(form)

        low, high = sorted([event.pk, other_event.pk])
        if action == "add":
            EventExclusion.objects.get_or_create(
                event_a_id=low,
                event_b_id=high,
                defaults={
                    "created_by": get_object_or_404(ObjectDB, pk=self.get_character()),
                    "creator_name": get_object_or_404(ObjectDB, pk=self.get_character()).key,
                },
            )
        else:
            EventExclusion.objects.filter(event_a_id=low, event_b_id=high).delete()

        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-event-exclusions", kwargs={"pk": event.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ClusterCreateView(CalendarAuthoringMixin, FormView):
    """Create a new EventCluster. Any logged-in puppeted character may create."""

    form_class = EventClusterForm
    template_name = "evennia_calendar/cluster_form.html"

    def check_permission(self, character_id, target):
        pass  # any puppet holder can create

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create New Cluster"
        context["form_action"] = reverse("evennia_calendar:calendar-cluster-create")
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        data = form.cleaned_data
        cluster = EventCluster.objects.create(
            creator=character,
            creator_name=character.key,
            title=data["title"],
            description=data.get("description", ""),
            is_locked=data.get("is_locked", False),
        )
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-cluster-detail", kwargs={"pk": cluster.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ClusterEditView(CalendarAuthoringMixin, FormView):
    """Edit an existing EventCluster. Permission: creator or staff."""

    form_class = EventClusterForm
    template_name = "evennia_calendar/cluster_form.html"

    def _get_cluster(self):
        if not hasattr(self, "_cluster"):
            self._cluster = _cluster_or_404(self.kwargs["pk"])
        return self._cluster

    def get_permission_target(self):
        return self._get_cluster()

    def check_permission(self, character_id, target):
        _check_cluster_permission(self.request, character_id, target)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_cluster()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cluster = self._get_cluster()
        context["page_title"] = f"Edit Cluster: {cluster.title}"
        context["cluster"] = cluster
        context["form_action"] = reverse(
            "evennia_calendar:calendar-cluster-edit", kwargs={"pk": cluster.pk}
        )
        return context

    def form_valid(self, form):
        cluster = self._get_cluster()
        data = form.cleaned_data
        cluster.title = data["title"]
        cluster.description = data.get("description", "")
        cluster.is_locked = data.get("is_locked", cluster.is_locked)
        cluster.save()
        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-cluster-detail", kwargs={"pk": cluster.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ClusterMembershipView(CalendarAuthoringMixin, FormView):
    """Add or remove a CalendarEvent from an EventCluster. Creator or staff."""

    form_class = EventClusterMembershipForm
    template_name = "evennia_calendar/cluster_membership_form.html"

    def _get_cluster(self):
        if not hasattr(self, "_cluster"):
            self._cluster = _cluster_or_404(self.kwargs["pk"])
        return self._cluster

    def get_permission_target(self):
        return self._get_cluster()

    def check_permission(self, character_id, target):
        _check_cluster_permission(self.request, character_id, target)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cluster = self._get_cluster()
        context["page_title"] = f"Manage Events: {cluster.title}"
        context["cluster"] = cluster
        context["member_events"] = cluster.events.filter(is_cancelled=False).order_by(
            "scheduled_time"
        )
        context["form_action"] = reverse(
            "evennia_calendar:calendar-cluster-members", kwargs={"pk": cluster.pk}
        )
        return context

    def form_valid(self, form):
        cluster = self._get_cluster()

        if cluster.is_locked:
            form.add_error(None, "Cannot modify membership of a locked cluster.")
            return self.form_invalid(form)

        event_id = form.cleaned_data["event_id"]
        action = form.cleaned_data["action"]

        event = CalendarEvent.objects.filter(pk=event_id, is_cancelled=False).first()
        if event is None:
            form.add_error("event_id", f"No active event with ID {event_id} found.")
            return self.form_invalid(form)

        if action == "add":
            existing_events = cluster.events.filter(is_cancelled=False)
            existing_flags = set(existing_events.values_list("is_staff_event", flat=True))
            if existing_flags and event.is_staff_event not in existing_flags:
                form.add_error(
                    None,
                    "All events in a cluster must share the same is_staff_event flag.",
                )
                return self.form_invalid(form)
            existing_times = set(existing_events.values_list("scheduled_time", flat=True))
            if existing_times and event.scheduled_time not in existing_times:
                form.add_error(
                    None,
                    "All events in a cluster must share the same "
                    "scheduled_time (parallel events).",
                )
                return self.form_invalid(form)
            event.cluster = cluster
            event.save(update_fields=["cluster"])
        else:
            if event.cluster_id == cluster.pk:
                event.cluster = None
                event.save(update_fields=["cluster"])

        return HttpResponseRedirect(
            reverse("evennia_calendar:calendar-cluster-members", kwargs={"pk": cluster.pk})
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))
