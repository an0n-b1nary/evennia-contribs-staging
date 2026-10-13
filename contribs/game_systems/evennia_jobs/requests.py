# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings-owned request forms and validation shared by all submission surfaces.

This module deliberately has no web dependencies or partner imports. Saved
submissions retain the normalized schema, including acknowledgement wording.
"""

import re
from copy import deepcopy

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TYPES = {"text", "longtext", "choice", "boolean"}


def request_forms(*, include_owned=False):
    """Return enabled, normalized forms; reject malformed configuration."""
    registry = getattr(settings, "JOBS_REQUEST_FORMS", {})
    if not isinstance(registry, dict):
        raise ImproperlyConfigured("JOBS_REQUEST_FORMS must be a dictionary.")
    result = {}
    for key, definition in registry.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ImproperlyConfigured("Request form keys must be stable lowercase identifiers.")
        if not isinstance(definition, dict):
            raise ImproperlyConfigured(f"Request form {key} must be a dictionary.")
        if set(definition) - {"label", "description", "enabled", "questions", "owner", "outcomes"}:
            raise ImproperlyConfigured(f"Unknown option in request form {key}.")
        if "outcomes" in definition:
            from evennia_jobs.models import RequestOutcome

            outcomes = definition["outcomes"]
            if (
                not isinstance(outcomes, (list, tuple))
                or not outcomes
                or any(outcome not in RequestOutcome.values for outcome in outcomes)
                or len(set(outcomes)) != len(outcomes)
            ):
                raise ImproperlyConfigured(f"Invalid review outcomes in request form {key}.")
        owner = definition.get("owner")
        if owner is not None and (not isinstance(owner, str) or not _KEY.fullmatch(owner)):
            raise ImproperlyConfigured(f"Invalid domain owner in request form {key}.")
        if type(definition.get("enabled", True)) is not bool:
            raise ImproperlyConfigured(f"Request form {key} needs a boolean enabled flag.")
        if definition.get("enabled", True) is False:
            continue
        form = deepcopy(definition)
        if "outcomes" in form:
            form["outcomes"] = list(form["outcomes"])
        form.setdefault("label", key.replace("_", " ").title())
        form.setdefault("description", "")
        if not isinstance(form["label"], str) or not isinstance(form["description"], str):
            raise ImproperlyConfigured(f"Request form {key} needs text labels.")
        questions = []
        seen = set()
        if not isinstance(form.get("questions"), (list, tuple)):
            raise ImproperlyConfigured(f"Request form {key} needs a question list.")
        for raw in form.get("questions", []):
            if isinstance(raw, (tuple, list)) and len(raw) == 2:
                raw = {"key": raw[0], "label": raw[1]}
            if not isinstance(raw, dict):
                raise ImproperlyConfigured(f"Invalid question in request form {key}.")
            if set(raw) - {
                "key",
                "label",
                "type",
                "required",
                "help_text",
                "max_length",
                "choices",
            }:
                raise ImproperlyConfigured(f"Unknown question option in {key}.")
            question = deepcopy(raw)
            name = question.get("key", "")
            if not isinstance(name, str) or not _KEY.fullmatch(name) or name in seen:
                raise ImproperlyConfigured(f"Invalid or duplicate question key in {key}.")
            seen.add(name)
            question.setdefault("label", name.replace("_", " ").title())
            question.setdefault("type", "longtext")
            question.setdefault("required", True)
            question.setdefault("help_text", "")
            question.setdefault("max_length", 10000)
            if not isinstance(question["type"], str) or question["type"] not in _TYPES:
                raise ImproperlyConfigured(f"Unknown question type in {key}.{name}.")
            if not isinstance(question["label"], str) or not isinstance(question["help_text"], str):
                raise ImproperlyConfigured(f"Question {key}.{name} needs text labels.")
            if type(question["required"]) is not bool:
                raise ImproperlyConfigured(f"Question {key}.{name} needs a boolean required flag.")
            if type(question["max_length"]) is not int or not 1 <= question["max_length"] <= 50000:
                raise ImproperlyConfigured(f"Invalid answer limit in {key}.{name}.")
            if question["type"] == "choice":
                choices = question.get("choices", [])
                if (
                    not choices
                    or not isinstance(choices, (list, tuple))
                    or any(
                        not isinstance(choice, str) or not choice or choice != choice.strip()
                        for choice in choices
                    )
                    or len(set(choices)) != len(choices)
                ):
                    raise ImproperlyConfigured(f"Invalid choices in {key}.{name}.")
                question["choices"] = list(choices)
            questions.append(question)
        if not questions:
            raise ImproperlyConfigured(f"Request form {key} needs at least one question.")
        form["questions"] = questions
        if not owner or include_owned:
            result[key] = form
    return result


def get_request_form(key, *, owner=None):
    """Resolve an enabled form, refusing unknown or disabled keys."""
    try:
        form = request_forms(include_owned=True)[key]
        if form.get("owner") and form["owner"] != owner:
            raise ValidationError("Use the owning feature to submit this request.")
        return form
    except KeyError as exc:
        raise ValidationError("That request form is unavailable.") from exc


def clean_answer(question, value):
    """Validate one answer identically for commands, web and programmatic callers."""
    if question["type"] == "boolean":
        if type(value) is bool:
            answer = value
        elif isinstance(value, str) and value.strip().lower() in {"yes", "true", "on", "1"}:
            answer = True
        elif (
            value is None
            or value == ""
            or (isinstance(value, str) and value.strip().lower() in {"no", "false", "off", "0"})
        ):
            answer = False
        else:
            raise ValidationError("Answer yes or no.")
        if question["required"] and not answer:
            raise ValidationError("This acknowledgement is required.")
        return answer
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("Enter a text answer.")
    answer = value.strip()
    if question["required"] and not answer:
        raise ValidationError("This question is required.")
    if len(answer) > question["max_length"]:
        raise ValidationError(f"Use at most {question['max_length']} characters.")
    if question["type"] == "choice" and answer and answer not in question["choices"]:
        raise ValidationError(f"Choose one of: {', '.join(question['choices'])}.")
    return answer


def clean_answers(schema, answers):
    """Validate a complete answer mapping and refuse unrecognized fields."""
    if not isinstance(answers, dict):
        raise ValidationError("Answers must be a dictionary.")
    questions = schema["questions"]
    if set(answers) - {question["key"] for question in questions}:
        raise ValidationError("Answers contain an unknown question.")
    cleaned, errors = {}, {}
    for question in questions:
        try:
            cleaned[question["key"]] = clean_answer(question, answers.get(question["key"]))
        except ValidationError as exc:
            errors[question["key"]] = exc.messages
    if errors:
        raise ValidationError(errors)
    return cleaned


def answer_rows(submission):
    """Return saved question wording and printable answers in their original order."""
    rows = []
    for question in submission.schema["questions"]:
        value = submission.answers.get(question["key"], "")
        if type(value) is bool:
            value = "Yes" if value else "No"
        rows.append({"label": question["label"], "value": value or "(not supplied)"})
    return rows
