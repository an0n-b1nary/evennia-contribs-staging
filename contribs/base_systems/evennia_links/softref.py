# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Soft-reference cascade compensation for integer-id bridge fields.

Cross-domain bridge models use a real FK to their *own* domain's model
and an integer soft-reference (PositiveBigIntegerField) for the *foreign*
domain model, so the bridge has no DB dependency on the optional partner app.
The downside: the DB's CASCADE rule doesn't fire when the foreign entity is
deleted. This helper compensates by registering a post_delete receiver that
deletes orphaned bridge rows.

Usage (call from AppConfig.ready(), unconditionally if the foreign model is
always present, or gated on the partner app being in INSTALLED_APPS)::

    from evennia_links import connect_soft_ref_cleanup

    class MyAppConfig(AppConfig):
        def ready(self):
            from django.conf import settings
            from myapp.models import SessionActivityLink

            label = getattr(settings, "MYAPP_TARGET_APP_LABEL", "target")
            if label in {a.split(".")[-1] for a in settings.INSTALLED_APPS}:
                from django.apps import apps
                TargetModel = apps.get_model(label, "TargetModel")
                connect_soft_ref_cleanup(TargetModel, SessionActivityLink, "target_id")

Semantics:
- Fires on **hard delete only**. Soft-archived records that are not hard-deleted
  retain their link rows — the historical link survives the archive.
- Idempotent: calling connect_soft_ref_cleanup with the same arguments
  multiple times is safe (Django deduplicates by dispatch_uid).

Why integer soft-references instead of ForeignKeys?
A real FK to an optional app creates a DB-level dependency on that app's
migration state. When the optional app is installed *after* the bridge
table already exists, migration tooling may fail to apply the FK constraint
retroactively. An integer field has no such dependency: the bridge table
always exists, the optional app can be installed in any order, and this
helper restores the cascade semantics at the Python level.
"""

from django.db.models.signals import post_delete


def connect_soft_ref_cleanup(target_model, bridge_model, field_name):
    """Register a post_delete receiver that cleans up orphaned bridge rows.

    When an instance of *target_model* is hard-deleted, any rows in
    *bridge_model* whose *field_name* column holds the deleted pk are
    deleted. This compensates for the missing DB cascade on integer
    soft-reference fields.

    Args:
        target_model: The Django model class whose deletions should trigger
            cleanup (e.g. a Scene model from an optional scenes contrib).
        bridge_model: The Django model class containing the soft-reference
            field (e.g. a link model that stores scene_id as an integer).
        field_name: The name of the integer field on *bridge_model* that
            holds *target_model* pks (e.g. ``"scene_id"``).
    """

    def _cleanup(sender, instance, **kwargs):
        bridge_model.objects.filter(**{field_name: instance.pk}).delete()

    post_delete.connect(
        _cleanup,
        sender=target_model,
        weak=False,
        dispatch_uid=f"softref:{bridge_model._meta.label}:{field_name}",
    )
