# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Only trusted templates enter msg_contents; player text is mapping data."""

from evennia_rp_contest import conf
from evennia_rp_rules.ruleset import get_ruleset
from evennia_rp_rules.vocabulary import get_vocabulary

MESSAGE_TYPE = {"type": "rp_test"}


def emit(room, template, mapping, *, actor=None):
    if room is not None:
        room.msg_contents((template, MESSAGE_TYPE.copy()), mapping=mapping, from_obj=actor)


def tag_name(key):
    tag = get_vocabulary().get(key) if key else None
    return tag.name if tag else key or ""


def test_values(record):
    ruleset = get_ruleset()
    stat = ruleset.stats.get(record.stat)
    return {
        "actor": record.actor_name,
        "stat": stat.name if stat else record.stat,
        "tag": f" ({tag_name(record.tag)})" if record.tag else "",
        "challenge": f" on #{record.challenge.number}" if record.challenge_id else "",
        "alternative": " (alternative approach)" if record.alternative else "",
        "attempt": f" (attempt {record.attempt_no})" if record.attempt_no > 1 else "",
        "outcome": record.detail["outcome"]["label"],
        "comment": f" — {record.comment}" if record.comment else "",
        "ratings": f" [{record.rating_display} vs {record.difficulty}]"
        if conf.get("RP_CONTEST_SHOW_RATINGS_TO_ROOM")
        else "",
    }


TEST_TEMPLATE = (
    "{actor} tests {stat}{tag}{challenge}{alternative}{attempt}: {outcome}.{ratings}{comment}"
)


def public_text(record):
    """Plain public line for a scene log; never includes the hidden breakdown."""
    return TEST_TEMPLATE.format_map(test_values(record))


def announce_test(record, *, result=None):
    emit(record.room, TEST_TEMPLATE, test_values(record), actor=record.character)


def announce_challenge(challenge, *, verb, actor=None):
    ruleset = get_ruleset()
    stat = ruleset.stats.get(challenge.stat_key)
    suggestion = ""
    if stat:
        suggestion = f" Suggested: {stat.name}"
        if challenge.tag:
            suggestion += f"/{tag_name(challenge.tag)}"
        suggestion += "."
    emit(
        challenge.room,
        "{actor} {verb} challenge #{number} ({difficulty}){once}: {prompt}{suggestion}",
        {
            "actor": actor.key if actor else "The system",
            "verb": verb,
            "number": challenge.number,
            "difficulty": challenge.difficulty,
            "once": " (once)" if challenge.once else "",
            "prompt": challenge.description,
            "suggestion": suggestion,
        },
        actor=actor,
    )
