# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cooperative standalone notification hook for hosts with Resources."""

from .notices import prepare_character


class ResourceSummaryCharacterMixin:
    """Place before DefaultCharacter in the typeclass method resolution order."""

    def at_post_puppet(self, **kwargs):
        """Deliver standalone resource summaries for the current character."""
        super().at_post_puppet(**kwargs)
        prepare_character(self)
