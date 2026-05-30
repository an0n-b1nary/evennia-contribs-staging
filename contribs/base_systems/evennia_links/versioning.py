# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Abstract base model for version history on any text field.

Concrete subclasses live in their respective domain apps and provide a
``parent`` ForeignKey to the model being versioned.

Each concrete subclass must define a ``parent`` ForeignKey to its parent
model and set ``unique_together = [("parent", "version_number")]``.

Usage::

    from evennia_links import AbstractVersion

    class PostVersion(AbstractVersion):
        parent = models.ForeignKey(
            Post, on_delete=models.CASCADE, related_name="versions"
        )

        class Meta(AbstractVersion.Meta):
            unique_together = [("parent", "version_number")]

    # Snapshot content before editing:
    PostVersion.create_version(post, old_content, editor=character)

    # Roll back to a prior version:
    PostVersion.rollback_to(post, version_number=3, editor=character)
"""

from django.db import models


class AbstractVersion(models.Model):
    """
    Abstract base for append-only version history on a text field.

    Version records snapshot the OLD content before each edit. The
    current/live content always lives on the parent model itself.
    Rolling back to version N creates a new version (N+1) whose content
    is a copy of version N — history is never rewritten.
    """

    version_number = models.PositiveIntegerField(help_text="Auto-incremented per parent object.")
    content = models.TextField(help_text="Full snapshot of the content at this version.")
    editor = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The character who made this edit.",
    )
    editor_name = models.CharField(
        max_length=255,
        help_text="Denormalized name of the editor for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_rollback = models.BooleanField(
        default=False,
        help_text="True if this version was created by a rollback operation.",
    )
    rolled_back_from = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="If is_rollback, the version number that was restored.",
    )

    class Meta:
        abstract = True
        ordering = ["-version_number"]  # noqa: RUF012

    def __str__(self):
        tag = " (rollback)" if self.is_rollback else ""
        return f"v{self.version_number} by {self.editor_name}{tag}"

    @classmethod
    def create_version(cls, parent, content, editor):
        """
        Create a new version record for the given parent.

        Args:
            parent: The Django model instance being versioned.
            content: The text content to snapshot (typically the OLD
                content before an edit is applied).
            editor: The ObjectDB instance (Character) who made the edit,
                or None for system-generated versions.

        Returns:
            The newly created version instance.
        """
        current_max = (
            cls.objects.filter(parent=parent)
            .aggregate(max_num=models.Max("version_number"))
            .get("max_num")
        ) or 0

        return cls.objects.create(
            parent=parent,
            version_number=current_max + 1,
            content=content,
            editor=editor,
            editor_name=editor.key if editor else "System",
        )

    @classmethod
    def rollback_to(cls, parent, version_number, editor):
        """
        Restore a previous version's content as a new append-only version.

        Args:
            parent: The Django model instance being versioned.
            version_number: The version number to restore.
            editor: The ObjectDB instance performing the rollback.

        Returns:
            The newly created rollback version instance.

        Raises:
            cls.DoesNotExist: If the target version_number doesn't exist.
        """
        target = cls.objects.get(parent=parent, version_number=version_number)

        current_max = (
            cls.objects.filter(parent=parent)
            .aggregate(max_num=models.Max("version_number"))
            .get("max_num")
        ) or 0

        return cls.objects.create(
            parent=parent,
            version_number=current_max + 1,
            content=target.content,
            editor=editor,
            editor_name=editor.key if editor else "System",
            is_rollback=True,
            rolled_back_from=version_number,
        )
