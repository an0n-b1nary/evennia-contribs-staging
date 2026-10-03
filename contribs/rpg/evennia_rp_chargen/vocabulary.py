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


__all__ = ["DBVocabulary", "ensure_tag"]
