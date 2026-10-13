# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Transactional submission and review services; no optional dependencies."""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from evennia_jobs.models import (
    Job,
    JobStatus,
    JobType,
    RequestDecision,
    RequestOutcome,
    RequestSubmission,
    RequestWithdrawal,
)
from evennia_jobs.requests import clean_answers, get_request_form
from evennia_jobs.signals import request_approved, request_reviewed, request_withdrawn
from evennia_links.transactions import atomic_objects


def review_fields(submission, viewer):
    """Partner context is never requested for nonstaff viewers."""
    from evennia_jobs.signals import request_review_context
    from evennia_links.collect import collect_dicts

    if submission is None or not is_staff_character(viewer):
        return {}
    fields = {}
    for provider in collect_dicts(
        request_review_context, sender=review_fields, submission=submission, viewer=viewer
    ).values():
        fields.update(provider)
    return fields


def is_staff_character(character):
    """Check the configured Jobs command lock, failing closed."""
    lock = getattr(settings, "JOBS_STAFF_LOCK", "cmd:perm(Builder)")
    expression = lock[4:] if lock.startswith("cmd:") else lock
    try:
        return bool(character and character.locks.check_lockstring(character, expression))
    except Exception:
        return False


@transaction.atomic
def submit_request(
    *, author, form_key, title, answers, job=None, expected_revision=None, owner=None
):
    """Create a structured ticket or append a revision requested by staff.

    Revision submissions require the latest revision number, protecting against
    stale web forms and concurrent command submissions. Old revisions and their
    decisions remain intact. Approval never enables another revision.
    """
    if not author or not author.pk:
        raise PermissionDenied("A character is required.")
    schema = get_request_form(form_key, owner=owner)
    cleaned = clean_answers(schema, answers)
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 255:
        raise ValidationError("Enter a title of 1 to 255 characters.")
    revision = 1
    if job is not None:
        Job.objects.filter(pk=job.pk).update(status=F("status"))
        job = Job.objects.select_for_update().get(pk=job.pk)
        if job.author_id != author.pk:
            raise PermissionDenied("Only the submitter can revise this request.")
        if title.strip() != job.title:
            raise ValidationError("The ticket title stays unchanged across revisions.")
        latest = job.submissions.select_for_update().order_by("-revision").first()
        if job.status == JobStatus.CLOSED or latest is None:
            raise ValidationError("This ticket cannot be revised.")
        if latest.revision != expected_revision or latest.form_key != form_key:
            raise ValidationError("This request has changed. Reload it before submitting.")
        if not latest.can_revise:
            raise ValidationError("Staff must request changes before a revision can be submitted.")
        revision = latest.revision + 1
        job.status = JobStatus.OPEN
        job.save(update_fields=["status", "updated_at"])
    else:
        job = Job.create_job(
            job_type=JobType.REQUEST,
            author=author,
            title=title.strip(),
            description=schema["description"] or schema["label"],
        )
    return RequestSubmission.objects.create(
        job=job, revision=revision, form_key=form_key, schema=schema, answers=cleaned
    )


@atomic_objects
def review_request(*, job, reviewer, outcome, reason, expected_revision, review_options=None):
    """Review exactly the latest revision and emit approval once, atomically.

    Repeating the same decision returns its original record without emitting
    again. Conflicting decisions and stale reviews are refused.
    """
    # Acquire the writer before reading the current revision on SQLite too.
    Job.objects.filter(pk=job.pk).update(status=F("status"))
    if not is_staff_character(reviewer):
        raise PermissionDenied("Only Jobs staff may review requests.")
    if outcome not in RequestOutcome.values:
        raise ValidationError("Choose a valid review outcome.")
    if review_options is not None and not isinstance(review_options, dict):
        raise ValidationError("Review options must be a dictionary.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 10000:
        raise ValidationError("Give a review explanation of 1 to 10,000 characters.")
    job = Job.objects.select_for_update().get(pk=job.pk)
    latest = job.submissions.select_for_update().order_by("-revision").first()
    if latest is None or latest.revision != expected_revision:
        raise ValidationError("This request has changed. Reload it before reviewing.")
    if outcome not in latest.schema.get("outcomes", RequestOutcome.values):
        raise ValidationError("That review outcome is unavailable for this form.")
    if RequestWithdrawal.objects.filter(submission=latest).exists():
        raise ValidationError("This revision was withdrawn and cannot be reviewed.")
    previous = RequestDecision.objects.filter(submission=latest).first()
    if previous:
        if previous.outcome == outcome:
            return previous
        raise ValidationError("This revision has already been reviewed.")
    if job.status == JobStatus.CLOSED:
        raise ValidationError("Reopen this ticket before reviewing it.")
    decision = RequestDecision.objects.create(
        submission=latest,
        reviewer=reviewer,
        reviewer_name=reviewer.key,
        outcome=outcome,
        reason=reason.strip(),
    )
    # Domain receivers validate and persist their own options transactionally.
    # These values are never put in the applicant's saved answers.
    decision.review_options = dict(review_options or {})
    job.mark_answered()
    if outcome == RequestOutcome.APPROVED:
        request_approved.send(sender=RequestSubmission, submission=latest, decision=decision)
    request_reviewed.send(sender=RequestSubmission, submission=latest, decision=decision)
    return decision


@transaction.atomic
def withdraw_request(*, job, author, expected_revision, reason=""):
    """Withdraw exactly the current pending revision; serialize against review."""
    Job.objects.filter(pk=job.pk).update(status=F("status"))
    job = Job.objects.select_for_update().get(pk=job.pk)
    if not author or job.author_id != author.pk:
        raise PermissionDenied("Only the submitter can withdraw this request.")
    latest = job.submissions.select_for_update().order_by("-revision").first()
    if latest is None or latest.revision != expected_revision:
        raise ValidationError("This request has changed. Reload before withdrawing.")
    if not isinstance(reason, str) or len(reason) > 10000:
        raise ValidationError("Use at most 10,000 characters for the reason.")
    previous = RequestWithdrawal.objects.filter(submission=latest).first()
    if previous:
        return previous
    if RequestDecision.objects.filter(submission=latest).exists():
        raise ValidationError("This revision has already been reviewed.")
    withdrawal = RequestWithdrawal.objects.create(
        submission=latest, actor=author, actor_name=author.key, reason=reason.strip()
    )
    job.mark_answered()
    request_withdrawn.send(sender=RequestSubmission, submission=latest, withdrawal=withdrawal)
    return withdrawal
