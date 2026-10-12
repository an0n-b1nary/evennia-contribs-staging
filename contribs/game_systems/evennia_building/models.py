from django.db import models


def character(**kwargs):
    return models.ForeignKey(
        "objects.ObjectDB", on_delete=models.SET_NULL, null=True, related_name="+", **kwargs
    )


class BuildProject(models.Model):
    owner = character()
    owner_name = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    purpose = models.CharField(max_length=20, default="home")
    state = models.CharField(max_length=20, default="draft", db_index=True)
    version = models.PositiveIntegerField(default=1)
    anchor = character()
    entrance_name = models.CharField(max_length=100, default="home")
    requested_environment = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class DraftRoom(models.Model):
    project = models.ForeignKey(BuildProject, on_delete=models.PROTECT, related_name="rooms")
    room = models.OneToOneField(
        "objects.ObjectDB", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    object_id = models.PositiveIntegerField()
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, related_name="children")
    floor = models.IntegerField(default=0)
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    entry = models.BooleanField(default=False)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["project", "floor", "x", "y"], name="building_room_cell_unique"
            )
        ]


class DraftDoor(models.Model):
    project = models.ForeignKey(BuildProject, on_delete=models.PROTECT, related_name="doors")
    source = models.ForeignKey(DraftRoom, on_delete=models.PROTECT, related_name="doors")
    target = models.ForeignKey(DraftRoom, on_delete=models.PROTECT, related_name="incoming")
    exit = models.OneToOneField(
        "objects.ObjectDB", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    object_id = models.PositiveIntegerField()
    outward = models.BooleanField(default=False)


class BuildSubmission(models.Model):
    project = models.ForeignKey(BuildProject, on_delete=models.PROTECT, related_name="submissions")
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField()
    fingerprint = models.CharField(max_length=64)
    jobs_submission_id = models.PositiveIntegerField(null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            from django.core.exceptions import ValidationError

            original = type(self).objects.get(pk=self.pk)
            immutable = ("project_id", "revision", "snapshot", "fingerprint")
            if any(getattr(original, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Submitted snapshots are immutable; create a fresh revision.")
            if (
                original.jobs_submission_id is not None
                and original.jobs_submission_id != self.jobs_submission_id
            ):
                raise ValidationError("A submission's Jobs binding cannot be replaced.")
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["project", "revision"], name="building_submission_revision_unique"
            )
        ]


class BuildReview(models.Model):
    submission = models.OneToOneField(
        BuildSubmission, on_delete=models.PROTECT, related_name="review"
    )
    outcome = models.CharField(max_length=20)
    actor = character()
    actor_name = models.CharField(max_length=255)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class EnvironmentApproval(models.Model):
    """Explicit staff consent to the environment in one immutable submission."""

    submission = models.OneToOneField(
        BuildSubmission, on_delete=models.PROTECT, related_name="environment_approval"
    )
    actor = character()
    actor_name = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=64)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class Property(models.Model):
    """One owner's boundary; multiple properties may share a future building."""

    owner = character()
    owner_name = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    promotion = models.OneToOneField(
        BuildSubmission, on_delete=models.PROTECT, related_name="property"
    )
    anchor = character()
    entrance = character()
    departure = character()
    locked = models.BooleanField(default=False)
    state = models.CharField(max_length=20, default="live")
    provenance = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class RoomOwnership(models.Model):
    room = models.OneToOneField(
        "objects.ObjectDB", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    object_id = models.PositiveIntegerField(unique=True)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="rooms")
    owner = character()


class Resident(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="residents")
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    can_install = models.BooleanField(default=False)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["property", "character"], name="building_resident_unique"
            )
        ]


class GuestInvitation(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="invitations")
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    state = models.CharField(max_length=20, default="pending")
    entry = models.BooleanField(default=True)
    maps = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["property", "character"], name="building_invitation_unique"
            )
        ]


class RoomOverride(models.Model):
    ownership = models.OneToOneField(
        RoomOwnership, on_delete=models.CASCADE, related_name="override"
    )
    allowed_character_ids = models.JSONField(default=list)


class RegionBuildPolicy(models.Model):
    region_id = models.PositiveIntegerField(unique=True)
    policy = models.CharField(max_length=20)


class BuildAudit(models.Model):
    project = models.ForeignKey(
        BuildProject, on_delete=models.PROTECT, null=True, related_name="audit"
    )
    property = models.ForeignKey(
        Property, on_delete=models.PROTECT, null=True, related_name="audit"
    )
    actor = character()
    actor_name = models.CharField(max_length=255)
    action = models.CharField(max_length=64)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
