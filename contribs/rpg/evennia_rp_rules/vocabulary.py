# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tag vocabulary: which tags (domains, elements, ...) exist right now.

The ruleset's `tags` are a seed. A game that lets tags grow at runtime (chargen
keeps them in the database so staff can add a domain without a deploy) points
`settings.RP_RULES_VOCABULARY` at a zero-argument factory returning anything
with this shape:

    class Vocabulary(Protocol):
        def tags(self, kind=None) -> list[TagDef]: ...
        def get(self, key) -> TagDef | None: ...
        def find(self, text, *, kind=None) -> TagDef: ...   # LookupError if no match

Commands resolve player input through `get_vocabulary().find()`. The pipeline
itself treats tags as opaque keys and never consults the vocabulary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from evennia_rp_rules._config import resolve_dotted, setting
from evennia_rp_rules.ruleset import Ruleset, TagDef, get_ruleset


@runtime_checkable
class Vocabulary(Protocol):
    def tags(self, kind: str | None = None) -> list[TagDef]: ...

    def get(self, key: str) -> TagDef | None: ...

    def find(self, text: str, *, kind: str | None = None) -> TagDef: ...


class RulesetVocabulary:
    """The ruleset's own `tags`, unchanged. The default vocabulary."""

    def __init__(self, ruleset: Ruleset | None = None):
        self.ruleset = ruleset or get_ruleset()

    def tags(self, kind: str | None = None) -> list[TagDef]:
        return [t for t in self.ruleset.tags.values() if kind is None or t.kind == kind]

    def get(self, key: str) -> TagDef | None:
        return self.ruleset.tags.get(key)

    def find(self, text: str, *, kind: str | None = None) -> TagDef:
        return self.ruleset.find_tag(text, kind=kind)


def get_vocabulary() -> Vocabulary:
    """The game's vocabulary: `settings.RP_RULES_VOCABULARY()`, else the ruleset's tags.

    Not cached, so a database-backed vocabulary is always current.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If the setting names
            something that can't be imported.
    """
    path = setting("RP_RULES_VOCABULARY")
    if not path:
        return RulesetVocabulary()
    try:
        factory = resolve_dotted(path)
    except (ImportError, AttributeError) as exc:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"RP_RULES_VOCABULARY: can't import {path!r}: {exc}") from exc
    return factory()


__all__ = ["RulesetVocabulary", "Vocabulary", "get_vocabulary"]
