# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One-switch account command for the same inbox used by the website."""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_links.notices import source_registry

from .context import from_command
from .services import effective_mode, mutate, project, set_preference


class CmdNotices(StrictSwitchMixin, MuxCommand):
    """Read personal alerts and source preferences.

    Usage:
      +notices
      +notices/read <notice>
      +notices/clear <notice>
      +notices/next <notice>
      +notices/history [<notice>]
      +notices/settings
      +notices/set <source>=<immediate|summary|off>

    Reading acknowledges the alert, not its source content or pending decision.
    Clear cannot dismiss an outstanding sought-seat decision. Resolve that at
    the source. Off suppresses new routine alerts; decisions remain in summaries.
    """

    key = "+notices"
    locks = "cmd:all()"
    switch_options = ("read", "clear", "history", "settings", "set", "next")

    def func(self):
        """Authorize explicit session scope and call shared projection services."""
        try:
            context = from_command(self.caller, self.session)
            switch = self.switches[0] if self.switches else ""
            if switch in {"read", "clear"}:
                item = mutate(context, self.args.strip(), switch)
                if switch == "read":
                    instructions = "\n".join(
                        f"{label}: {command or url or 'Follow the source instructions.'}"
                        for label, command, url in item.actions
                    )
                    self.msg("\n".join(value for value in (item.text, instructions) if value))
                else:
                    self.msg("Notice cleared.")
            elif switch == "set":
                set_preference(context, self.lhs.strip(), self.rhs.strip() if self.rhs else "")
                self.msg("Notice preference saved.")
            elif switch == "settings":
                self.msg(
                    "Notice preferences (off keeps decisions in summaries):\n"
                    + "\n".join(
                        f"{slug}: {effective_mode(context.account, slug)}; decisions: {effective_mode(context.account, slug, True)}"
                        for slug in source_registry()
                    )
                )
            else:
                cursor = self.args.strip() if switch in {"next", "history"} else None
                page = project(
                    context, "history" if switch == "history" else "unread", cursor=cursor
                )
                if switch == "history":
                    sections = [("Notice history", page)]
                else:
                    sections = [
                        ("Awaiting your decision", [item for item in page if item.outstanding]),
                        ("Routine alerts", [item for item in page if not item.outstanding]),
                    ]
                lines = []
                for title, rows in sections:
                    lines.append(title)
                    lines.extend(
                        f"{r.notice.public_ref} [{r.label}] "
                        f"{'Pending decision' if r.outstanding else 'Read' if not r.unread else 'Unread'}: {r.text}"
                        for r in rows
                    )
                    if not rows:
                        lines.append("No notices. Source activity will appear here.")
                if getattr(page, "next_cursor", None):
                    switch_name = "history" if switch == "history" else "next"
                    lines.append(f"Next page: +notices/{switch_name} {page.next_cursor}")
                self.msg("\n".join(lines))
        except ValueError as exc:
            self.msg(str(exc))
