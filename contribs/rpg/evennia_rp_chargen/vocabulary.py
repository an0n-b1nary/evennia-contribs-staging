# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The database tag vocabulary: the ruleset's tags plus whatever staff add.

    RP_RULES_VOCABULARY = "evennia_rp_chargen.vocabulary.DBVocabulary"

Tags are the ruleset's `tags`, overlaid by `TagDefinition` rows: a row with
the same key replaces the ruleset's version (a renamed domain), an archived
row hides it, and new rows add tags. So the vocabulary works before anything
is seeded, and grows at runtime without a deploy.
"""

from __future__ import annotations

from evennia_rp_chargen.models import TagDefinition
from evennia_rp_rules.ruleset import TagDef, get_ruleset, match_spelling


class DBVocabulary:
    def _all(self) -> dict[str, TagDef]:
        tags = dict(get_ruleset().tags)
        for row in TagDefinition.all_objects.all():
            if row.is_archived:
                tags.pop(row.key, None)
            else:
                tags[row.key] = row.as_tagdef()
        return tags

    def tags(self, kind: str | None = None) -> list[TagDef]:
        found = [t for t in self._all().values() if kind is None or t.kind == kind]
        return sorted(found, key=lambda t: (t.kind, t.name.casefold()))

    def get(self, key: str) -> TagDef | None:
        return self._all().get(key)

    def find(self, text: str, *, kind: str | None = None) -> TagDef:
        return match_spelling(self.tags(kind), text, kind or "tag")


def spelling_conflicts(key: str, spellings) -> list[tuple[str, str]]:
    """Other tags already using any of `spellings`, as (spelling, owner key) pairs.

    All kinds share one namespace, as in the ruleset, so `+test` can always
    resolve a full name. The ruleset checks its own seed; this checks rows.
    """
    wanted = {str(spelling).strip().casefold() for spelling in spellings if str(spelling).strip()}
    return sorted(
        (spelling, tag.key)
        for tag in DBVocabulary()._all().values()
        if tag.key != key
        for spelling in {s.casefold() for s in tag.spellings()} & wanted
    )


def conflict_message(conflicts) -> str:
    used = "; ".join(f"{spelling!r} is already used by {owner!r}" for spelling, owner in conflicts)
    return f"Tag names are unique across kinds: {used}."


def ensure_tag(tag: TagDef) -> TagDefinition:
    """The `TagDefinition` row for a vocabulary tag, created from the ruleset if needed."""
    row, _ = TagDefinition.all_objects.get_or_create(
        key=tag.key,
        defaults={
            "name": tag.name,
            "kind": tag.kind,
            "aliases": list(tag.aliases),
            "description": tag.description,
        },
    )
    return row


__all__ = ["DBVocabulary", "conflict_message", "ensure_tag", "spelling_conflicts"]
