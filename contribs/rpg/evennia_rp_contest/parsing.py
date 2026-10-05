# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Parse player-led approaches, optional suggestions, and multi-kind tags."""

from dataclasses import dataclass

from evennia_rp_contest import conf
from evennia_rp_rules.ruleset import get_ruleset, match_spelling
from evennia_rp_rules.vocabulary import get_vocabulary


class ContestError(ValueError):
    """A player-readable refusal or syntax error."""


@dataclass(frozen=True)
class TestRequest:
    stat: str
    tag: str | None = None
    challenge_number: int | None = None
    comment: str = ""


@dataclass(frozen=True)
class ChallengeRequest:
    difficulty: str
    description: str
    stat: str | None = None
    tag: str | None = None
    once: bool = False


def number(text):
    text = text.strip().removeprefix("#")
    if not text.isdecimal() or int(text) < 1:
        raise ContestError("Give a challenge number such as #2.")
    return int(text)


def limited(text):
    if len(text) > conf.get("RP_CONTEST_COMMENT_MAX"):
        raise ContestError(f"Keep text to {conf.get('RP_CONTEST_COMMENT_MAX')} characters.")
    return text.strip()


def find_tag(text):
    kind = conf.get("RP_CONTEST_TAG_KIND")
    kinds = [kind] if isinstance(kind, str) else kind
    candidates = [t for t in get_vocabulary().tags() if kinds is None or t.kind in kinds]
    # An explicit kind:key disambiguates a cross-kind spelling collision.
    if ":" in text:
        selected, text = text.split(":", 1)
        candidates = [t for t in candidates if t.kind.casefold() == selected.strip().casefold()]
    needle = text.strip().casefold()
    exact = [t for t in candidates if needle in {s.casefold() for s in t.spellings()}]
    matches = exact or [
        t for t in candidates if any(s.casefold().startswith(needle) for s in t.spellings())
    ]
    if len(matches) > 1:
        choices = ", ".join(f"{t.kind}:{t.key} ({t.name})" for t in matches)
        raise ContestError(f"Which tag did you mean? Choose {choices}.")
    try:
        return match_spelling(candidates, text, "tag")
    except LookupError as exc:
        raise ContestError(str(exc)) from exc


def approach(text):
    stat_text, separator, tag_text = text.partition("/")
    try:
        stat = get_ruleset().find_stat(stat_text.strip()).key
    except LookupError as exc:
        raise ContestError(str(exc)) from exc
    tag = find_tag(tag_text.strip()).key if separator else None
    return stat, tag


def parse_test(text):
    body, _, comment = text.partition("~")
    challenge = None
    if "=" in body:
        ref, body = body.split("=", 1)
        challenge = number(ref)
    stat, tag = approach(body)
    return TestRequest(stat, tag, challenge, limited(comment))


def parse_challenge(text, *, once=False):
    body, separator, prompt = text.partition("~")
    if not separator or not prompt.strip():
        raise ContestError("Usage: +test/set <difficulty>[=<stat>[/<tag>]]~<prompt>")
    difficulty, suggestion, proposed = body.partition("=")
    if not difficulty.strip():
        raise ContestError("Give a difficulty rating or preset.")
    stat, tag = approach(proposed) if suggestion else (None, None)
    return ChallengeRequest(difficulty.strip(), limited(prompt), stat, tag, once)
