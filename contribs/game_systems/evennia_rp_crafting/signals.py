# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional partner seams; crafting never imports the providers."""

from django.dispatch import Signal

collect_facets = Signal()  # providers return {key: facet implementation}
page_read = Signal()  # actor, item, record, number, canonical; return a display line
