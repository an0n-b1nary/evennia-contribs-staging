# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Single-switch Jobs commands and dotted revision addresses with comments."""

import re

from django.core.exceptions import ValidationError
from evennia.commands.default.muxcommand import MuxCommand


class JobCommand(MuxCommand):
    """Reject extra or invalid switches before MuxCommand can ignore them."""

    switch_options = ()

    def at_pre_cmd(self):
        if super().at_pre_cmd():
            return True
        raw = self.args.strip()
        if not raw.startswith("/"):
            return False
        head, *tail = raw.split(maxsplit=1)
        switch = head[1:].lower()
        if "/" in switch:
            self.msg("Use one switch at a time.")
            return True
        matches = [option for option in self.switch_options if option == switch] or [
            option for option in self.switch_options if option.startswith(switch)
        ]
        if len(matches) != 1:
            self.msg(f"Unknown or ambiguous switch. See help {self.key} for usage.")
            return True
        # Keep argument and comment case; only switch matching is case-insensitive.
        self.args = f"/{switch}" + (f" {tail[0]}" if tail else "")
        return False


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
