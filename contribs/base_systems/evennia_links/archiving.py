# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Abstract mixin for soft-archive support on any model.

Concrete models inherit AbstractArchived to gain archive/unarchive
functionality with a default manager that hides archived records.

Usage::

    from evennia_links import AbstractArchived

    class Scene(AbstractArchived):
        title = models.CharField(max_length=200)
        # ...

    # Default queryset excludes archived records:
    Scene.objects.all()  # only non-archived

    # Include archived records explicitly:
    Scene.objects.include_archived().all()

    # Or use the secondary manager for admin/staff access:
    Scene.all_objects.all()

    # Archive a record:
    scene.archive(editor=character)

    # Restore:
    scene.unarchive()
"""

from django.db import models
from django.utils import timezone


class ArchivedQuerySet(models.QuerySet):
    """QuerySet that filters out archived records by default."""

    def include_archived(self):
        """Return a new queryset that includes archived records."""
        return self.model.all_objects.using(self.db).all()


class ArchivedManager(models.Manager):
    """Default manager that excludes archived records."""

    def get_queryset(self):
        return ArchivedQuerySet(self.model, using=self._db).filter(is_archived=False)

    def include_archived(self):
        """Convenience shortcut: return unfiltered queryset."""
        return self.model.all_objects.using(self.db).all()


class AbstractArchived(models.Model):
    """
    Abstract mixin providing soft-archive functionality.

    Archived records are hidden from the default manager but remain in
    the database. Use ``archive(editor)`` and ``unarchive()`` to toggle
    the archive state.

    Managers:
        objects: Default manager — excludes archived records.
        all_objects: Secondary manager — includes all records.
    """

    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The character who archived this record.",
    )
    archived_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized name of the archiver for display after deletion.",
    )

    objects = ArchivedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def archive(self, editor=None):
        """
        Soft-archive this record.

        Args:
            editor: The ObjectDB instance (Character) performing the
                archive, or None for system-initiated archives.
        """
        self.is_archived = True
        self.archived_at = timezone.now()
        self.archived_by = editor
        self.archived_by_name = editor.key if editor else "System"
        self.save(
            update_fields=[
                "is_archived",
                "archived_at",
                "archived_by",
                "archived_by_name",
            ]
        )

    def unarchive(self):
        """Restore this record from the archive."""
        self.is_archived = False
        self.archived_at = None
        self.archived_by = None
        self.archived_by_name = ""
        self.save(
            update_fields=[
                "is_archived",
                "archived_at",
                "archived_by",
                "archived_by_name",
            ]
        )
