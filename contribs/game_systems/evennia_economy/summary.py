# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Compatibility entry point for the standalone first-puppet summary."""

from .notices import prepare_character


def notify_economy_summary(character):
    """Return true if the combined income and stipend line was sent in standalone mode."""
    return prepare_character(character)
