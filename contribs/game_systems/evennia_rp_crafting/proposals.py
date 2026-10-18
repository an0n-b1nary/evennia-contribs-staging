# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player-proposed Patterns: approving a Jobs proposal creates one the proposer knows.

The form is an ordinary Jobs request form, so the questionnaire, revisions and
withdrawal are Jobs'. Crafting reads the answers only when staff approve, inside
the review transaction: a refusal rolls the decision back so staff can request
changes instead. A requested combination is never opened automatically.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from evennia_links.characters import is_playable
from evennia_links.guests import is_guest

from . import conf
from .behaviours import text
from .errors import CraftingError
from .models import NicheDefinition, Pattern, PatternKnowledge
from .pattern_form import FORM_KEY
from .patterns import _learn, _log, _require, _reserve, visible

REQUIRED = ("name", "description", "niches")


def form_key():
    return getattr(settings, "RP_CRAFTING_PATTERN_FORM", FORM_KEY)


def _answer(submission, key):
    value = submission.answers.get(key, "")
    return value if isinstance(value, str) else ""


def niche_keys(value):
    """Match each comma-separated entry to an unarchived niche by key or name."""
    niches = list(NicheDefinition.objects.filter(archived=False))
    keys, unknown = [], []
    for entry in (part.strip() for part in re.split(r"[,;]", value or "")):
        if not entry:
            continue
        match = next(
            (
                niche
                for niche in niches
                if entry.casefold() in (niche.key.casefold(), niche.name.casefold())
            ),
            None,
        )
        if match is None:
            unknown.append(entry)
        elif match.key not in keys:
            keys.append(match.key)
    if unknown:
        raise CraftingError(f"Unknown niches: {', '.join(unknown)}.")
    if not keys:
        raise CraftingError("Name at least one niche the Pattern serves.")
    return keys


def preview(submission):
    """The Pattern approval would create, or the CraftingError that blocks it."""
    questions = {question["key"] for question in submission.schema.get("questions", [])}
    if set(REQUIRED) - questions:
        raise CraftingError("This form lacks the name, description or niches question.")
    name = text(_answer(submission, "name"), "Pattern name", 80, required=True)
    key = slugify(name)[:80].strip("-_")
    if not key:
        raise CraftingError("The Pattern name needs letters or numbers for its key.")
    others = Pattern.objects.exclude(proposal_submission_id=submission.pk)
    if others.filter(key=key).exists():
        raise CraftingError(f"The Pattern key {key} is taken; keys are permanent.")
    if any(row.casefold() == name.casefold() for row in others.values_list("name", flat=True)):
        raise CraftingError(f"A Pattern named {name} already exists.")
    return {
        "key": key,
        "name": name,
        "description": text(_answer(submission, "description"), "Description", 2000),
        "niches": niche_keys(_answer(submission, "niches")),
    }


def create_from(submission, reviewer):
    """Create the proposed Pattern at Spreading, known to its proposer; idempotent."""
    existing = Pattern.objects.filter(proposal_submission_id=submission.pk).first()
    if existing:
        return existing
    proposer = submission.job.author
    if proposer is None:
        raise CraftingError("The proposing character no longer exists.")
    _reserve(proposer)
    _require(reviewer, staff=True)
    if not is_playable(proposer) or is_guest(proposer):
        raise CraftingError("Only a playable, non-guest character's proposal becomes a Pattern.")
    values = preview(submission)
    try:
        # A concurrent approval of another proposal may have taken the key.
        with transaction.atomic():
            pattern = Pattern.objects.create(
                **values,
                stage_changed_at=timezone.now(),
                created_by_id=reviewer.pk,
                proposal_submission_id=submission.pk,
            )
    except IntegrityError:
        raise CraftingError(
            f"The Pattern key {values['key']} is taken; keys are permanent."
        ) from None
    _log(
        pattern,
        Pattern.Stage.SPREADING,
        reviewer,
        f"Approved proposal, request #{submission.job.job_number}",
    )
    _learn(proposer, pattern, PatternKnowledge.Via.PROPOSAL, granted_by_id=reviewer.pk)
    if visible(proposer):
        transaction.on_commit(
            lambda: proposer.msg(
                f"Your proposal is approved: you know the Pattern {pattern.name}. "
                f"See +pattern/info {pattern.key}."
            )
        )
    return pattern


def approved(sender, submission, decision, **kwargs):
    """Jobs `request_approved`, inside the review transaction."""
    if submission.form_key != form_key():
        return
    try:
        create_from(submission, decision.reviewer)
    except CraftingError as exc:
        raise ValidationError(f"{exc} Request changes, or create the Pattern by hand.") from None


def review_context(sender, *, submission, viewer, **kwargs):
    """Staff see what approval would create, or why it can't, before deciding."""
    if submission.form_key != form_key() or not conf.is_staff(viewer):
        return {}
    existing = Pattern.objects.filter(proposal_submission_id=submission.pk).first()
    if existing:
        return {"crafting": {"Pattern": f"{existing.name} ({existing.key}), created on approval"}}
    try:
        values = preview(submission)
    except CraftingError as exc:
        return {"crafting": {"Approval": f"Blocked: {exc}"}}
    return {
        "crafting": {
            "Approval creates": f"{values['name']} ({values['key']}), Spreading",
            "Niches": ", ".join(values["niches"]),
            "Combinations": "none; staff add tested ones with +pattern/combo",
        }
    }
