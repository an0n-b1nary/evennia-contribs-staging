# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Single-switch Jobs commands and dotted revision addresses with comments."""

import re

from django.core.exceptions import ValidationError
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin


class JobCommand(StrictSwitchMixin, MuxCommand):
    """Reject extra or invalid switches before MuxCommand can ignore them."""

    switch_options = ()


def split_comment(text):
    """Split at the first hash with whitespace on both sides, preserving dbrefs."""
    match = re.search(r"(?<=\s)#(?=\s)", text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def revision_address(text):
    """Return positive ticket and revision numbers from ``[#]N.R``."""
    match = re.fullmatch(r"#?([1-9][0-9]*)\.([1-9][0-9]*)", text)
    if match is None:
        raise ValidationError("Use a dotted ticket revision, such as #12.3.")
    try:
        return int(match[1]), int(match[2])
    except ValueError as exc:
        raise ValidationError("Ticket and revision numbers are too long.") from exc
