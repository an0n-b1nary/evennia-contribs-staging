# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Abstract base models for cross-system bridge ("link") models.

Two tiers let the creator-audit block be optional at the schema level:

- AbstractLink — the minimal base: created_at + create_link().
  Use when a link is created automatically (e.g. by a signal listener)
  and recording a human author adds no value.

- AbstractAuthoredLink(AbstractLink) — adds created_by / created_by_name.
  Use when a link is created by a deliberate player or staff action and
  auditing who made it is useful.

Every concrete subclass must:

1. Declare its two ForeignKey fields (the entities being linked).
2. Set ``link_fields = ("<fk_a_name>", "<fk_b_name>")``.
3. Add ``unique_together = [("<fk_a_name>", "<fk_b_name>")]`` in its Meta.
4. Inherit Meta from the chosen base: ``class Meta(AbstractLink.Meta)``.

Usage::

    from evennia_links import AbstractAuthoredLink

    class ItemCharacterLink(AbstractAuthoredLink):
        item = models.ForeignKey("myapp.Item", on_delete=models.CASCADE,
                                 related_name="character_links")
        character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE,
                                      related_name="+")
        link_fields = ("item", "character")

        class Meta(AbstractAuthoredLink.Meta):
            unique_together = [("item", "character")]

    # Create idempotently (returns (instance, created) tuple):
    link, created = ItemCharacterLink.create_link(item, character, linked_by=requester)

Bridge models live in the *consumer* app, not in this package. This package
only provides the abstract bases; concrete models are defined in the game that
installs the contribs that need to be linked.

See the README for the bridge-ownership convention and the soft-dependency
pattern for optional inter-contrib integrations.
"""

from django.db import models


class AbstractLink(models.Model):
    """
    Minimal abstract base for any two-entity bridge model.

    Provides created_at and a generic idempotent create_link() classmethod.
    Subclasses declare their two ForeignKeys and set link_fields.
    """

    created_at = models.DateTimeField(auto_now_add=True)

    link_fields = ()  # subclass sets, e.g. ("scene", "thread")

    class Meta:
        abstract = True
        ordering = ["created_at"]  # noqa: RUF012

    @classmethod
    def create_link(cls, a, b, **extra_defaults):
        """
        Idempotent factory: get_or_create a link between a and b.

        Args:
            a: The first entity instance (mapped to link_fields[0]).
            b: The second entity instance (mapped to link_fields[1]).
            **extra_defaults: Additional keyword arguments passed as defaults
                to get_or_create (e.g. computed fields like advance_notice_met).

        Returns:
            tuple: (link_instance, created_bool)
        """
        a_field, b_field = cls.link_fields
        return cls.objects.get_or_create(
            **{a_field: a, b_field: b},
            defaults=extra_defaults,
        )


class AbstractAuthoredLink(AbstractLink):
    """
    Abstract base for link models that record who created them.

    Adds created_by (nullable FK to objects.ObjectDB) and created_by_name
    (denormalized for resilience after character deletion).

    Use this tier when a link is created by a deliberate player or staff
    action and auditing the creator is valuable. Use AbstractLink when the
    link is created automatically (e.g. by a signal listener).
    """

    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who created the link.",
    )
    created_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True
        ordering = ["created_at"]  # noqa: RUF012

    @classmethod
    def create_link(cls, a, b, linked_by=None, **extra_defaults):
        """
        Idempotent factory: get_or_create a link between a and b, recording
        the creating character.

        Args:
            a: The first entity instance (mapped to link_fields[0]).
            b: The second entity instance (mapped to link_fields[1]).
            linked_by: ObjectDB character creating the link (optional).
            **extra_defaults: Additional defaults forwarded to get_or_create.

        Returns:
            tuple: (link_instance, created_bool)
        """
        defaults = {
            "created_by": linked_by,
            "created_by_name": linked_by.key if linked_by else "",
            **extra_defaults,
        }
        return super().create_link(a, b, **defaults)
