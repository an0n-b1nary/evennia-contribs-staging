# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
# Generated manually — add SceneCalendarLink model.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("evennia_calendar", "0001_initial"),
        ("objects", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="SceneCalendarLink",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by_name",
                    models.CharField(
                        blank=True,
                        max_length=255,
                    ),
                ),
                (
                    "scene_id",
                    models.PositiveBigIntegerField(
                        db_index=True,
                        help_text="PK of the Scene associated with this calendar event.",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Character who created the link.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="objects.objectdb",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        help_text="The calendar event associated with this scene.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scene_links",
                        to="evennia_calendar.calendarevent",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "abstract": False,
                "unique_together": {("event", "scene_id")},
            },
        ),
    ]
