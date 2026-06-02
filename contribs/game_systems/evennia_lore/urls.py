# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Website URL patterns for evennia_lore.

Include at a path of your choice::

    from django.urls import include, path
    urlpatterns += [path("lore/", include("evennia_lore.urls"))]

URL names: lore-list, lore-create, lore-compendium, lore-queue, lore-lean,
           lore-detail, lore-edit, lore-history, lore-diff, lore-approve, lore-reject.
"""

from django.urls import path

from evennia_lore.views import (
    LoreApprovalQueueView,
    LoreApproveView,
    LoreCompendiumView,
    LoreCreateView,
    LoreDetailView,
    LoreEditView,
    LoreLeanView,
    LoreListView,
    LoreRejectView,
    LoreVersionDiffView,
    LoreVersionHistoryView,
)

urlpatterns = [
    path("", LoreListView.as_view(), name="lore-list"),
    path("new/", LoreCreateView.as_view(), name="lore-create"),
    path("mine/", LoreCompendiumView.as_view(), name="lore-compendium"),
    path("queue/", LoreApprovalQueueView.as_view(), name="lore-queue"),
    path("lean/", LoreLeanView.as_view(), name="lore-lean"),
    path("<int:pk>/", LoreDetailView.as_view(), name="lore-detail"),
    path("<int:pk>/edit/", LoreEditView.as_view(), name="lore-edit"),
    path("<int:pk>/history/", LoreVersionHistoryView.as_view(), name="lore-history"),
    path(
        "<int:pk>/diff/<int:version_number>/",
        LoreVersionDiffView.as_view(),
        name="lore-diff",
    ),
    path("<int:pk>/approve/", LoreApproveView.as_view(), name="lore-approve"),
    path("<int:pk>/reject/", LoreRejectView.as_view(), name="lore-reject"),
]
