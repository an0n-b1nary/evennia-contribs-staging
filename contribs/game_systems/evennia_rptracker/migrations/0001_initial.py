import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create RPSession, RPSessionPartner, and RPSessionSceneLink tables.

    RPSessionSceneLink uses an integer scene_id (no FK to a scenes app), so
    this migration has no dependency on any optional partner contrib.
    """

    initial = True

    dependencies = [
        ("objects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RPSession",
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
                    "character_name",
                    models.CharField(
                        blank=True,
                        help_text="Denormalized character name for display after deletion.",
                        max_length=255,
                    ),
                ),
                (
                    "room_name",
                    models.CharField(
                        blank=True,
                        help_text="Denormalized room name for display after deletion.",
                        max_length=255,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("active", "Active"),
                            ("completed", "Completed"),
                            ("flagged", "Flagged"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=10,
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When tracking began (pending state).",
                    ),
                ),
                (
                    "activated_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the session became ACTIVE (activation threshold met).",
                        null=True,
                    ),
                ),
                (
                    "ended_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the session was completed or flagged.",
                        null=True,
                    ),
                ),
                (
                    "pose_count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Number of poses recorded during this session.",
                    ),
                ),
                (
                    "ended_manually",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "True if the player explicitly ended this session. "
                            "Too many manual ends in a day triggers an auto-flag."
                        ),
                    ),
                ),
                (
                    "xp_awarded",
                    models.BooleanField(
                        default=False,
                        help_text="True once the XP batch has processed this session.",
                    ),
                ),
                (
                    "xp_week",
                    models.CharField(
                        blank=True,
                        help_text="ISO week string (e.g. '2026-W14') when XP was awarded.",
                        max_length=10,
                    ),
                ),
                (
                    "flag_reason",
                    models.TextField(
                        blank=True,
                        help_text="Staff or auto-generated reason for flagging this session.",
                    ),
                ),
                (
                    "flagged_by_name",
                    models.CharField(
                        blank=True,
                        help_text="Denormalized name for the flagging staff member.",
                        max_length=255,
                    ),
                ),
                ("flagged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "character",
                    models.ForeignKey(
                        help_text="The character whose RP activity this session tracks.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="objects.objectdb",
                    ),
                ),
                (
                    "flagged_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Staff character who flagged this session, or None for auto-flags.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="objects.objectdb",
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        help_text="The IC room where this session started.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="objects.objectdb",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
                "indexes": [
                    models.Index(fields=["character", "status"], name="rptracker_rpsess_char_status"),
                    models.Index(fields=["status", "started_at"], name="rptracker_rpsess_status_start"),
                ],
            },
        ),
        migrations.CreateModel(
            name="RPSessionPartner",
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
                    "partner_name",
                    models.CharField(
                        blank=True,
                        help_text="Denormalized partner name for display after deletion.",
                        max_length=255,
                    ),
                ),
                (
                    "pose_count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Approximate count of times this partner was detected as active.",
                    ),
                ),
                (
                    "partner",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="objects.objectdb",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partners",
                        to="evennia_rptracker.rpsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-pose_count"],
            },
        ),
        migrations.AddConstraint(
            model_name="rpsessionpartner",
            constraint=models.UniqueConstraint(
                fields=["session", "partner"],
                name="rpsessionpartner_unique_session_partner",
            ),
        ),
        migrations.CreateModel(
            name="RPSessionSceneLink",
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
                    "scene_id",
                    models.PositiveBigIntegerField(
                        db_index=True,
                        help_text="PK of the Scene that was active in the room during the session.",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        help_text="The RPSession that overlapped with this scene.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scene_links",
                        to="evennia_rptracker.rpsession",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="rpsessionscenelink",
            constraint=models.UniqueConstraint(
                fields=["session", "scene_id"],
                name="rpsessionscenelink_unique_session_scene",
            ),
        ),
    ]
