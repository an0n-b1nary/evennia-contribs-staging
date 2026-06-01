# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Job and JobComment models for the staff ticket system.

Player-submitted tickets (+request, +bug, +issue) and staff-to-staff
discussion tickets (+discuss). Job type distinguishes audience and workflow.

Design notes:
- job_number is a global auto-incrementing integer (not per-type) so staff
  can reference any ticket by a single unambiguous ID (e.g. "+jobs 42").
- author / assignee use FK to ObjectDB with denormalized *_name fields —
  display works even if the character is later deleted.
- ISSUE tickets hide the reporter identity from non-staff callers; the
  author FK is always stored but filtered in the command display layer.
- No AbstractArchived — jobs are *closed*, not archived. Closed status is
  the terminal state; no soft-delete is needed.
- No AbstractVersion — job descriptions are immutable after creation.
  Corrections happen via comments, not edits, which preserves audit trail.

Conceptual pattern adapted from Evennia's base_systems/ingame_reports
contrib (credit: Evennia contributors).
"""

from django.db import IntegrityError, models, transaction
from django.db.models import Case, IntegerField, Max, Value, When
from django.utils import timezone

# Bounded retries for allocating a unique job_number under concurrent creation.
# Each retry re-reads Max(job_number); the unique constraint turns a lost race
# into an IntegrityError we recover from rather than a corrupted sequence.
_CREATE_JOB_MAX_RETRIES = 5


class JobType(models.TextChoices):
    REQUEST = "request", "Request"
    BUG = "bug", "Bug"
    ISSUE = "issue", "Issue"
    DISCUSS = "discuss", "Discuss"


class JobStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_REVIEW = "in_review", "In Review"
    ANSWERED = "answered", "Answered"
    CLOSED = "closed", "Closed"


class JobPriority(models.TextChoices):
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


# Priority-ranking weights used by ``Job.objects.by_priority()``. Lower
# integers sort first, so URGENT (0) precedes HIGH (1) precedes NORMAL (2).
_PRIORITY_RANK = {
    JobPriority.URGENT: 0,
    JobPriority.HIGH: 1,
    JobPriority.NORMAL: 2,
}


class JobManager(models.Manager):
    """Manager exposing :meth:`by_priority` for urgency-ordered queries.

    The default ``Meta.ordering`` is by ``created_at`` only. A naive
    ``order_by("-priority")`` sorts alphabetically on the enum string
    values, which yields ``urgent, normal, high`` — almost correct but
    with ``normal`` and ``high`` swapped. This manager annotates a
    numeric ``priority_rank`` and orders by it, then falls back to
    ``created_at`` so older tickets surface first within a priority.
    """

    def by_priority(self):
        whens = [When(priority=value, then=Value(rank)) for value, rank in _PRIORITY_RANK.items()]
        return (
            self.get_queryset()
            .annotate(priority_rank=Case(*whens, default=Value(99), output_field=IntegerField()))
            .order_by("priority_rank", "created_at")
        )


class Job(models.Model):
    """
    A single staff ticket.

    Created by players (+request, +bug, +issue) or staff (+discuss).
    Managed by staff via +jobs. The job_number is a globally unique
    human-readable ID; it never resets or reuses.
    """

    job_number = models.PositiveIntegerField(
        unique=True,
        help_text="Auto-incremented globally. Used as the human-readable ticket ID.",
    )
    job_type = models.CharField(
        max_length=10,
        choices=JobType.choices,
        db_index=True,
    )
    status = models.CharField(
        max_length=10,
        choices=JobStatus.choices,
        default=JobStatus.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=JobPriority.choices,
        default=JobPriority.NORMAL,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField()

    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The character who submitted this ticket.",
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized author name for display after deletion.",
    )

    assignee = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The staff member assigned to handle this ticket.",
    )
    assignee_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized assignee name for display after deletion.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when status transitions to Closed.",
    )

    objects = JobManager()

    class Meta:
        # Default ordering is by age only. Callers that want urgency-first
        # ordering should use ``Job.objects.by_priority()`` — a naive
        # ``order_by("-priority")`` sorts alphabetically on the enum's
        # string values and produces urgent/normal/high (wrong).
        ordering = ["created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["job_type", "status"]),
        ]

    def __str__(self):
        return f"[#{self.job_number}] {self.get_job_type_display()}: {self.title}"

    @classmethod
    def create_job(cls, job_type, author, title, description):
        """
        Create a new ticket, assigning the next global job_number.

        The next number is read as ``Max(job_number) + 1``. Because that read
        and the insert are not a single atomic step, two concurrent creators
        can pick the same number; the ``unique=True`` constraint then rejects
        the loser with an ``IntegrityError``. We wrap each attempt in a
        savepoint (``transaction.atomic``) and retry up to
        ``_CREATE_JOB_MAX_RETRIES`` times, re-reading the max each pass, so a
        lost race re-allocates cleanly instead of surfacing an error.

        Args:
            job_type: One of JobType choices.
            author: ObjectDB (Character) instance, or None.
            title: str — short ticket title.
            description: str — full description body.

        Returns:
            The newly created Job instance.

        Raises:
            IntegrityError: if a unique job_number could not be allocated
                within the retry budget.
        """
        author_name = author.key if author else "Unknown"
        for _attempt in range(_CREATE_JOB_MAX_RETRIES):
            current_max = cls.objects.aggregate(max_num=Max("job_number")).get("max_num") or 0
            try:
                # Savepoint so a collision rolls back just this insert, leaving
                # any enclosing transaction usable for the next attempt.
                with transaction.atomic():
                    return cls.objects.create(
                        job_number=current_max + 1,
                        job_type=job_type,
                        title=title,
                        description=description,
                        author=author,
                        author_name=author_name,
                    )
            except IntegrityError:
                continue
        raise IntegrityError(
            f"Could not allocate a unique job_number after " f"{_CREATE_JOB_MAX_RETRIES} attempts."
        )

    def mark_in_review(self):
        """Transition to IN_REVIEW."""
        self.status = JobStatus.IN_REVIEW
        self.save(update_fields=["status", "updated_at"])

    def mark_answered(self):
        """Transition to ANSWERED."""
        self.status = JobStatus.ANSWERED
        self.save(update_fields=["status", "updated_at"])

    def close(self):
        """Transition to CLOSED and record closed_at timestamp."""
        self.status = JobStatus.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])

    def reopen(self):
        """Reopen a CLOSED ticket back to OPEN."""
        self.status = JobStatus.OPEN
        self.closed_at = None
        self.save(update_fields=["status", "closed_at", "updated_at"])


class JobComment(models.Model):
    """
    A comment on a job ticket.

    Comments are append-only — no edits or soft-delete. is_staff_only
    controls visibility: staff-only comments are hidden from the original
    submitter when they view their own ticket.
    """

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized author name for display after deletion.",
    )
    content = models.TextField()
    is_staff_only = models.BooleanField(
        default=False,
        help_text="If True, this comment is hidden from the ticket submitter.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        tag = " [staff-only]" if self.is_staff_only else ""
        return f"Comment on #{self.job.job_number} by {self.author_name}{tag}"

    @classmethod
    def create_comment(cls, job, author, content, is_staff_only=False):
        """
        Append a comment to *job*.

        Args:
            job: The parent :class:`Job`.
            author: ObjectDB (Character) instance, or None.
            content: str — comment body.
            is_staff_only: Whether this comment is hidden from the submitter.

        Returns:
            The newly created JobComment instance.
        """
        return cls.objects.create(
            job=job,
            author=author,
            author_name=author.key if author else "Unknown",
            content=content,
            is_staff_only=is_staff_only,
        )
