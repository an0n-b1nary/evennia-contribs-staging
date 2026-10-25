# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One-switch commands and whitespace-delimited trailing comments."""

import re

from evennia_links.command_syntax import StrictSwitchMixin as SingleSwitchMixin  # noqa: F401


def split_comment(text):
    """Split the first whitespace-surrounded hash, preserving dbrefs and later hashes."""
    match = re.search(r"(?<=\s)#(?=\s)", text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.end() :].strip()
