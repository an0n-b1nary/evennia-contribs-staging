# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
# Generated manually — add LoreInspirationCredit model.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("evennia_lore", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoreInspirationCredit",
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
                (
                    "character_id",
                    models.PositiveIntegerField(
                        db_index=True,
                        help_text="ObjectDB pk of the character who receives the inspiration credit.",
                    ),
                ),
                (
                    "character_name",
                    models.CharField(
                        blank=True,
                        help_text="Denormalized character name for display after deletion.",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "link",
                    models.ForeignKey(
                        help_text="The LoreSceneLink that generated this credit.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inspiration_credits",
                        to="evennia_lore.lorescenelink",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "unique_together": {("link", "character_id")},
            },
        ),
    ]
