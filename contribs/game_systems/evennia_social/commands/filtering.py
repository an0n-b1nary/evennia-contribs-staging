# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Player filtering — +ignore/+mute command.

Account-level ignore list management. Filtering enforcement happens in
``SocialCharacterMixin.msg()`` (typeclasses.py), not here.
"""

from evennia.commands.default.muxcommand import MuxCommand


class CmdIgnore(MuxCommand):
    """
    Manage your ignore list.

    Usage:
        +ignore                     - View your ignore list
        +ignore <character>         - Add someone to your ignore list
        +ignore/remove <character>  - Remove someone from your ignore list
        +ignore/clear               - Clear your entire ignore list
        +mute <character>           - Alias for +ignore

    Ignoring a player filters their content across the game. Poses and
    says are replaced with a muted placeholder; whispers are suppressed
    entirely; pages are blocked. Ignore operates at the account level —
    ignoring one character ignores all of that player's alts.

    Staff messages always bypass ignore filters.
    """

    key = "+ignore"
    aliases = ["+mute"]  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        caller = self.caller
        account = caller.account
        if not account:
            caller.msg("You must be logged in to use this command.")
            return

        if "remove" in self.switches:
            self._remove(caller, account)
        elif "clear" in self.switches:
            self._clear(caller, account)
        elif self.switches:
            caller.msg(f"Unknown switch '/{self.switches[0]}'. See |whelp +ignore|n for usage.")
        elif self.args.strip():
            self._add(caller, account)
        else:
            self._view(caller, account)

    def _view(self, caller, account):
        """Display the current ignore list."""
        ignore_list = account.db.ignore_list or []
        if not ignore_list:
            caller.msg("Your ignore list is empty.")
            return

        from evennia.accounts.models import AccountDB

        width = 70
        lines = [f"|w+{'=' * (width - 2)}+|n"]
        header = " Ignore List "
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        for i, acct_id in enumerate(ignore_list, 1):
            try:
                ignored_acct = AccountDB.objects.get(id=acct_id)
                # Show character names associated with this account
                chars = ignored_acct.db._playable_characters or []
                char_names = ", ".join(c.key for c in chars if c) or "no characters"
                lines.append(f" {i}. {ignored_acct.key} ({char_names})")
            except AccountDB.DoesNotExist:
                lines.append(f" {i}. Unknown (Account #{acct_id})")

        lines.append(f"|w{'-' * width}|n")
        count = len(ignore_list)
        lines.append(
            f" {count} player{'s' if count != 1 else ''} ignored. "
            "Use |w+ignore/remove <name>|n to unblock."
        )
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        caller.msg("\n".join(lines))

    def _add(self, caller, account):
        """Add a player to the ignore list."""
        target = caller.search(self.args.strip())
        if not target:
            return

        if target == caller:
            caller.msg("You can't ignore yourself.")
            return

        target_account = target.account
        if not target_account:
            # Character exists but no connected account — try the stored
            # account reference for offline characters.
            target_account = target.db.account
        if not target_account:
            caller.msg("Could not determine that character's account.")
            return

        ignore_list = account.db.ignore_list or []
        if target_account.id in ignore_list:
            caller.msg(f"You are already ignoring {target.key}.")
            return

        ignore_list.append(target_account.id)
        account.db.ignore_list = ignore_list
        caller.msg(
            f"Now ignoring |w{target.key}|n. Their poses and says will "
            "appear as muted placeholders."
        )

    def _remove(self, caller, account):
        """Remove a player from the ignore list."""
        if not self.args.strip():
            caller.msg("Usage: |w+ignore/remove <character>|n")
            return

        target = caller.search(self.args.strip())
        if not target:
            return

        target_account = target.account
        if not target_account:
            target_account = target.db.account
        if not target_account:
            caller.msg("Could not determine that character's account.")
            return

        ignore_list = account.db.ignore_list or []
        if target_account.id not in ignore_list:
            caller.msg(f"You are not ignoring {target.key}.")
            return

        ignore_list.remove(target_account.id)
        account.db.ignore_list = ignore_list
        caller.msg(f"No longer ignoring |w{target.key}|n.")

    def _clear(self, caller, account):
        """Clear the entire ignore list."""
        ignore_list = account.db.ignore_list or []
        if not ignore_list:
            caller.msg("Your ignore list is already empty.")
            return

        count = len(ignore_list)
        account.db.ignore_list = []
        caller.msg(f"Ignore list cleared. Removed {count} player{'s' if count != 1 else ''}.")
