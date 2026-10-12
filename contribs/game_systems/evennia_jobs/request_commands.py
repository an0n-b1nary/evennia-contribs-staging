# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A resumable in-game questionnaire for the shared Jobs request registry."""

from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from evennia.utils.eveditor import EvEditor

from evennia_jobs.models import Job, RequestOutcome
from evennia_jobs.requests import clean_answer, get_request_form, request_forms
from evennia_jobs.review import review_request, submit_request, withdraw_request

_DRAFT = "jobs_request_draft"
_SWITCHES = {
    "forms",
    "form",
    "answer",
    "edit",
    "preview",
    "submit",
    "cancel",
    "resume",
    "revise",
    "withdraw",
}
_EDITOR = "jobs_request_editor"


def _editor_context(caller):
    draft = caller.attributes.get(_DRAFT)
    context = caller.attributes.get(_EDITOR)
    if not draft or not context or draft.get("draft_id") != context["draft_id"]:
        raise ValidationError("This questionnaire has changed. Reopen the answer editor.")
    question = next(q for q in draft["schema"]["questions"] if q["key"] == context["key"])
    return draft, question


def _answer_load(caller):
    """Load an existing answer into the persistent multiline editor."""
    draft, question = _editor_context(caller)
    return draft["answers"].get(question["key"], "")


def _answer_save(caller, buffer):
    """Save through shared validation, refusing a replaced questionnaire."""
    try:
        draft, question = _editor_context(caller)
        draft["answers"][question["key"]] = clean_answer(question, buffer)
        caller.attributes.add(_DRAFT, dict(draft))
    except ValidationError as exc:
        caller.msg("; ".join(exc.messages))
        return False
    caller.msg("Answer saved. Use :q to return to the questionnaire.")
    return True


def _answer_quit(caller):
    """Close the editor and display the next question."""
    caller.attributes.remove(_EDITOR)
    draft = caller.attributes.get(_DRAFT)
    if draft:
        _prompt(caller, draft)


def _prompt(caller, draft):
    questions = draft["schema"]["questions"]
    pending = [q for q in questions if q["key"] not in draft["answers"]]
    if not pending:
        caller.msg("All questions answered. Use +request/preview, then +request/submit.")
        return
    question = pending[0]
    text = f"{question['key']}: {question['label']}"
    if question["help_text"]:
        text += f"\n{question['help_text']}"
    if question["type"] == "choice":
        text += f"\nChoices: {', '.join(question['choices'])}"
    elif question["type"] == "boolean":
        text += "\nAnswer yes or no."
    text += f"\nUse +request/answer {question['key']}=<answer>"
    if not question["required"]:
        text += " (optional; leave the answer empty to skip)"
    if question["type"] in {"text", "longtext"}:
        text += f"\nFor multiple lines, use +request/edit {question['key']}."
    caller.msg(text)


def handle_request(command):
    """Handle structured request switches; return whether one was recognized."""
    switches = set(command.switches)
    if not switches & _SWITCHES:
        return False
    caller = command.caller
    try:
        if "withdraw" in switches:
            parts = command.lhs.split()
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ValidationError("Usage: +request/withdraw <ticket> <revision>=<reason>")
            job = Job.objects.filter(job_number=int(parts[0])).first()
            if not job:
                raise ValidationError("No such ticket.")
            withdraw_request(
                job=job, author=caller, expected_revision=int(parts[1]), reason=command.rhs or ""
            )
            caller.msg("Request withdrawn. Its history is preserved; you may revise it.")
            return True
        if "forms" in switches:
            lines = ["Request forms:"]
            for key, form in request_forms().items():
                lines.append(f"  {key}: {form['label']}")
            lines.append("Start: +request/form <key>=<title>. Plain +request is also available.")
            caller.msg("\n".join(lines))
            return True
        if "cancel" in switches:
            caller.attributes.remove(_DRAFT)
            caller.msg("Questionnaire cancelled. Submitted tickets are unchanged.")
            return True
        if "form" in switches or "revise" in switches:
            if caller.attributes.has(_DRAFT):
                raise ValidationError("Finish your questionnaire or use +request/cancel first.")
            job, revision, answers = None, None, {}
            if "revise" in switches:
                if not command.args.strip().isdigit():
                    raise ValidationError("Usage: +request/revise <ticket number>")
                job = Job.objects.filter(
                    job_number=int(command.args.strip()), author=caller
                ).first()
                latest = job.submissions.last() if job else None
                if not latest or not latest.can_revise:
                    raise ValidationError("No request awaiting your revision was found.")
                form_key, title, revision = latest.form_key, job.title, latest.revision
                schema = get_request_form(form_key)
                # Acknowledgements must be explicitly renewed on every revision.
                answers = {
                    q["key"]: latest.answers[q["key"]]
                    for q in schema["questions"]
                    if q["type"] != "boolean" and q["key"] in latest.answers
                }
            else:
                form_key = command.lhs.strip()
                title = (command.rhs or "").strip()
                schema = get_request_form(form_key)
                if not title or len(title) > 255:
                    raise ValidationError(
                        "Usage: +request/form <key>=<title of 1 to 255 characters>"
                    )
            draft = {
                "draft_id": uuid4().hex,
                "form_key": form_key,
                "title": title,
                "schema": schema,
                "answers": answers,
                "job_id": job.pk if job else None,
                "revision": revision,
            }
            caller.attributes.add(_DRAFT, draft)
            caller.msg(f"{schema['label']}: {title}\n{schema['description']}")
            _prompt(caller, draft)
            return True
        draft = caller.attributes.get(_DRAFT)
        if not draft:
            raise ValidationError("No questionnaire in progress. Use +request/forms to choose one.")
        if "edit" in switches:
            key = command.args.strip()
            question = next((q for q in draft["schema"]["questions"] if q["key"] == key), None)
            if question is None or question["type"] not in {"text", "longtext"}:
                raise ValidationError(
                    "Use +request/edit <text question key>; choices and acknowledgements use /answer."
                )
            caller.attributes.add(_EDITOR, {"draft_id": draft["draft_id"], "key": key})
            EvEditor(
                caller,
                loadfunc=_answer_load,
                savefunc=_answer_save,
                quitfunc=_answer_quit,
                key=f"Request: {question['label']}",
                persistent=True,
            )
        elif "answer" in switches:
            key = command.lhs.strip()
            question = next((q for q in draft["schema"]["questions"] if q["key"] == key), None)
            if question is None or command.rhs is None:
                raise ValidationError("Usage: +request/answer <question key>=<answer>")
            draft["answers"][key] = clean_answer(question, command.rhs)
            caller.attributes.add(_DRAFT, dict(draft))
            _prompt(caller, draft)
        elif "preview" in switches:
            lines = [draft["title"]]
            for question in draft["schema"]["questions"]:
                value = draft["answers"].get(question["key"], "(unanswered)")
                if type(value) is bool:
                    value = "Yes" if value else "No"
                lines.append(f"{question['label']}: {value}")
            lines.append("Edit with +request/answer <key>=<answer>; submit with +request/submit.")
            caller.msg("\n".join(lines))
        elif "submit" in switches:
            # Refuse schema changes during a questionnaire rather than recording
            # consent against wording the player has never seen.
            if get_request_form(draft["form_key"]) != draft["schema"]:
                raise ValidationError(
                    "This form has changed. Cancel and restart the questionnaire."
                )
            job = Job.objects.get(pk=draft["job_id"]) if draft["job_id"] else None
            submission = submit_request(
                author=caller,
                form_key=draft["form_key"],
                title=draft["title"],
                answers=dict(draft["answers"]),
                job=job,
                expected_revision=draft["revision"],
            )
            caller.attributes.remove(_DRAFT)
            caller.msg(
                f"Ticket #{submission.job.job_number}, revision {submission.revision}, submitted."
            )
        else:
            _prompt(caller, draft)
    except (ValidationError, PermissionDenied) as exc:
        caller.msg("; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
    return True


def handle_review(command):
    """Handle explicit staff decisions against a specified revision."""
    actions = {
        "approve": RequestOutcome.APPROVED,
        "decline": RequestOutcome.DECLINED,
        "revise": RequestOutcome.CHANGES_REQUESTED,
    }
    action = next((key for key in actions if key in command.switches), None)
    if action is None:
        return False
    try:
        parts = command.lhs.split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts) or not command.rhs:
            raise ValidationError(f"Usage: +jobs/{action} <ticket> <revision>=<explanation>")
        job = Job.objects.filter(job_number=int(parts[0])).first()
        if not job:
            raise ValidationError("No such ticket.")
        decision = review_request(
            job=job,
            reviewer=command.caller,
            outcome=actions[action],
            reason=command.rhs,
            expected_revision=int(parts[1]),
        )
        command.caller.msg(
            f"Ticket #{job.job_number}: {decision.get_outcome_display()} (revision {parts[1]})."
        )
    except (ValidationError, PermissionDenied) as exc:
        command.caller.msg(
            "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
    return True


def format_submissions(job):
    """Render every revision and its decision using screenreader-friendly text."""
    lines = []
    for submission in job.submissions.select_related("decision"):
        lines.append(f"\n{submission.schema['label']} — revision {submission.revision}")
        for row in submission.answer_rows:
            lines.append(f"{row['label']}: {row['value']}")
        if hasattr(submission, "withdrawal"):
            withdrawal = submission.withdrawal
            lines.append(f"Withdrawn by {withdrawal.actor_name}: {withdrawal.reason}")
        elif hasattr(submission, "decision"):
            decision = submission.decision
            lines.append(
                f"{decision.get_outcome_display()} by {decision.reviewer_name} "
                f"at {decision.created_at:%Y-%m-%d %H:%M} UTC: {decision.reason}"
            )
        else:
            lines.append("Awaiting review.")
    return "\n".join(lines)
