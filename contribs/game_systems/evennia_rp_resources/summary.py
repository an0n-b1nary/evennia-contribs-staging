# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Compatibility entry points for standalone first-puppet summaries."""

from .notices import grouped_gains, prepare_character
from .notices import latest_receipt as latest_receipt


def gains_text(character, week):
    """Format positive grants for a completed week."""
    return ", ".join(grouped_gains(character, [week]).get(week, ())) or "none"


def notify_resource_summary(character):
    """Return true if the current weekly award was sent in standalone mode."""
    return prepare_character(character, kind="weekly")


def notify_plot_summary(character):
    """Return true if a paid plot award was sent in standalone mode."""
    return prepare_character(character, kind="plot")
