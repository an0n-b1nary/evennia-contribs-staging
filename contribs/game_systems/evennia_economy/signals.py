# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.dispatch import Signal

asset_providers = Signal()  # {kind: provider}; see assets.py for the protocol
economy_figures = Signal()  # {provider: staff-readable figures}
