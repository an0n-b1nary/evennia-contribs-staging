# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from .summary import notify_resource_summary


class ResourceSummaryCharacterMixin:
    """Place before DefaultCharacter; cooperative, no ordering requirement."""

    def at_post_puppet(self, **kwargs):
        super().at_post_puppet(**kwargs)
        notify_resource_summary(self)
