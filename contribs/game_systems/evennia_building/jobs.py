"""Optional Jobs adapter. Answers identify a Building snapshot, never its content."""

from django.core.exceptions import ValidationError
from evennia_jobs.models import RequestSubmission
from evennia_jobs.review import submit_request
from evennia_jobs.signals import request_approved, request_reviewed, request_withdrawn

from .models import BuildSubmission
from .request_form import FORM, FORM_KEY  # noqa: F401


def answers_for(submission):
    return {
        "snapshot": submission.fingerprint,
        "summary": f"{submission.snapshot['name']} — revision {submission.revision}, {len(submission.snapshot['rooms'])} rooms",
        "link": f"/building/submissions/{submission.pk}/",
    }


def create_request(submission, actor, previous):
    old = (
        RequestSubmission.objects.filter(pk=previous.jobs_submission_id).first()
        if previous and previous.jobs_submission_id
        else None
    )
    revise = old is not None and old.can_revise
    title = old.job.title if revise else submission.snapshot["name"]
    linked = submit_request(
        author=actor,
        form_key=FORM_KEY,
        title=title,
        answers=answers_for(submission),
        job=old.job if revise else None,
        expected_revision=old.revision if revise else None,
        owner="evennia_building",
    )
    submission.jobs_submission_id = linked.pk
    submission.save(update_fields=["jobs_submission_id"])


def _binding(submission):
    if submission.form_key != FORM_KEY:
        return None
    record = BuildSubmission.objects.filter(jobs_submission_id=submission.pk).first()
    if (
        not record
        or submission.schema.get("owner") != "evennia_building"
        or submission.job.author_id != record.project.owner_id
        or submission.answers != answers_for(record)
    ):
        raise ValidationError(
            "This ticket is not bound to an authentic Building snapshot. Review it through Building."
        )
    return record


def approved(sender, submission, decision, **kwargs):
    _binding(submission)


def reviewed(sender, submission, decision, **kwargs):
    record = _binding(submission)
    if record:
        from .services import _record_review

        _record_review(record, decision.reviewer, decision.outcome, decision.reason)


def withdrawn(sender, submission, withdrawal, **kwargs):
    record = _binding(submission)
    if record:
        from .services import _record_review

        _record_review(record, withdrawal.actor, "withdrawn", withdrawal.reason)


def connect():
    request_approved.connect(approved, dispatch_uid="building.jobs.approved", weak=False)
    request_reviewed.connect(reviewed, dispatch_uid="building.jobs.reviewed", weak=False)
    request_withdrawn.connect(withdrawn, dispatch_uid="building.jobs.withdrawn", weak=False)
