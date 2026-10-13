# SPDX-License-Identifier: BSD-3-Clause
from django.apps import AppConfig


class ModerationConfig(AppConfig):
    name = "evennia_moderation"
    verbose_name = "Moderation and admissions"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        from evennia_jobs.signals import (
            request_review_context,
            request_review_form,
            request_reviewed,
        )

        from evennia_links.communication import communication_requested
        from evennia_moderation.admissions import admission_review_fields, review_admission
        from evennia_moderation.config import register_settings
        from evennia_moderation.policy import communication_policy

        register_settings()
        request_reviewed.connect(review_admission, dispatch_uid="moderation.admission", weak=False)
        request_review_context.connect(
            admission_review_fields, dispatch_uid="moderation.review-context", weak=False
        )
        from evennia_moderation.review import add_review_fields

        request_review_form.connect(
            add_review_fields, dispatch_uid="moderation.review-form", weak=False
        )
        communication_requested.connect(
            communication_policy, dispatch_uid="moderation.communication", weak=False
        )
