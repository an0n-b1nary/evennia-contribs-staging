# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Screen-reader helpers, accessible form bases, and MXP utilities for Evennia.

Public API:

    from evennia_accessibility import (
        uses_screenreader,
        plain_list,
        describe_icon,
        describe_priority,
        AccessibleForm,
        AccessibleModelForm,
        absolute_web_url,
        mxp_link,
    )

See `README.md` for installation, settings, and usage examples.
"""

from .accessibility import describe_icon, describe_priority, plain_list, uses_screenreader
from .forms import AccessibleForm, AccessibleModelForm
from .mxp import absolute_web_url, mxp_link

__version__ = "0.1.0"

__all__ = [
    "AccessibleForm",
    "AccessibleModelForm",
    "absolute_web_url",
    "describe_icon",
    "describe_priority",
    "mxp_link",
    "plain_list",
    "uses_screenreader",
]
