# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Authenticated explicit-scope views; GET never acknowledges activity."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from .context import from_web
from .forms import PreferenceForm
from .services import mutate, project, set_preference


def _page(request, template, **context):
    return TemplateResponse(request, f"evennia_notices/{template}.html", context)


@login_required
def inbox(request, history=False):
    """List only account and explicitly selected character projections."""
    context = from_web(request)
    cursor = request.GET.get("cursor")
    page = project(context, "history" if history else "unread", cursor=cursor)
    notices = page if history else [item for item in page if not item.outstanding]
    pending = [] if history else [item for item in page if item.outstanding]
    return _page(
        request,
        "list",
        notices=notices,
        pending=pending,
        next_cursor=getattr(page, "next_cursor", None),
        history=history,
        selected_character=context.character,
    )


@login_required
def detail(request, public_ref):
    """Display a safe detail without modifying read state."""
    context = from_web(request)
    item = next(iter(project(context, "all", public_ref=public_ref)), None)
    if item is None:
        raise Http404
    return _page(request, "detail", item=item)


@login_required
@require_POST
def change(request, public_ref, operation):
    """Recheck ownership, visibility and live outstanding state on every POST."""
    try:
        mutate(from_web(request), public_ref, operation)
    except ValueError as exc:
        raise Http404 from exc
    return redirect("evennia_notices:inbox")


@login_required
def preferences(request):
    """Edit the shared account preference using a closed validated form."""
    form = PreferenceForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        set_preference(from_web(request), **form.cleaned_data)
        return redirect("evennia_notices:preferences")
    return _page(request, "preferences", form=form)
