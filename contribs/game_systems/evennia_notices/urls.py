# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public opaque tokens, never database IDs."""

from django.urls import path

from . import views

app_name = "evennia_notices"
urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("history/", views.inbox, {"history": True}, name="history"),
    path("preferences/", views.preferences, name="preferences"),
    path("<str:public_ref>/", views.detail, name="detail"),
    path("<str:public_ref>/read/", views.change, {"operation": "read"}, name="read"),
    path("<str:public_ref>/clear/", views.change, {"operation": "clear"}, name="clear"),
]
