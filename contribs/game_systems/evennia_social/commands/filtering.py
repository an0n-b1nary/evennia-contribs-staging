# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Named personal boundaries; all enforcement lives in evennia_social.ignore."""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_links.identity import comms_identity
from evennia_social import ignore
from evennia_social.social import find_character


class CmdIgnore(StrictSwitchMixin, MuxCommand):
    """
    Manage your ignore list.

    Usage:
        +ignore                     - View your entries
        +ignore <character>         - Hide this character's posts and contact
        +ignore/full <character>    - Hide the whole player, including alts
        +ignore/except <character>  - Show posts, but still block contact
        +ignore/boards hide         - Hide ignored characters' board posts
        +ignore/boards show         - Use a placeholder for ignored board posts
        +ignore/channels hide       - Hide ignored channel lines entirely
        +ignore/channels show       - Use a placeholder for ignored channel lines
        +ignore/remove <character>  - Remove the entry made under this name
        +ignore/clear               - Remove every entry, including earlier ignores
        +mute <character>           - Alias for +ignore

    Posts are room poses, says, OOC, IC channel lines, crafting events and board
    posts. Hidden posts become muted placeholders. For boards and channels,
    ``show`` means placeholders, never the ignored content. Both preferences
    are shared by your account. Contact (pages, whispers, summons, joins, direct
    combat and crafting proposals) is blocked even for an exception. OOC
    channel lines from an ignored player stay filtered, including exceptions;
    IC channels show excepted characters' posts. Staff senders bypass filtering;
    staff readers also see every board and channel message. Channel history
    and web channel logs bypass the live filter and may show ignored content.

    A character entry overrides /full. /except also works without /full.
    /full can reveal alts through filtering: use it for boundaries, never
    to discover who plays whom. Replies and lists name only your entries.
    Earlier full ignores have no recorded name and require /clear.
    """

    switch_options = ("boards", "channels", "full", "except", "remove", "clear")
    key = "+ignore"
    aliases = ["+mute"]  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def __init__(self, **kwargs):
        if not getattr(settings, "SOCIAL_IGNORE_MUTE_ALIAS", True):
            kwargs.setdefault("aliases", [])
        super().__init__(**kwargs)

    def func(self):
        caller = self.caller
        account = ignore.account_for(caller)
        if not account:
            caller.msg("You must be logged in to use this command.")
            return
        if "boards" in self.switches or "channels" in self.switches:
            kind = "boards" if "boards" in self.switches else "channels"
            label = "board posts" if kind == "boards" else "channel lines"
            preference = self.args.strip().lower()
            if preference not in (ignore.HIDE, ignore.SHOW):
                caller.msg(f"Usage: +ignore/{kind} hide or +ignore/{kind} show")
                return
            try:
                setter = (
                    ignore.set_boards_preference
                    if kind == "boards"
                    else ignore.set_channels_preference
                )
                changed = setter(account, preference)
            except ignore.PolicyChangeError:
                caller.msg("Ignore settings could not be saved. Please try again.")
                return
            except ValueError as exc:
                caller.msg(str(exc))
                return
            if not changed:
                if preference == ignore.HIDE:
                    caller.msg(
                        f"Your {kind[:-1]} preference is already set to hide ignored {label}."
                    )
                else:
                    caller.msg(f"Your {kind[:-1]} preference is already set to show placeholders.")
            elif preference == ignore.HIDE:
                caller.msg(f"Ignored {label} will now be hidden.")
            else:
                caller.msg(f"Ignored {label} will now use placeholders.")
            return
        if "clear" in self.switches:
            try:
                count = ignore.clear(account)
            except ignore.PolicyChangeError:
                caller.msg("Ignore settings could not be saved. Please try again.")
                return
            caller.msg(f"Ignore list cleared. Removed {count} entries.")
            return
        if not self.args.strip() and not self.switches:
            self._view(caller, account)
            return
        target, error = find_character(self.args.strip())
        if error:
            caller.msg(error)
            return
        if "remove" in self.switches:
            try:
                removed = ignore.remove_entry(account, target)
            except ignore.PolicyChangeError:
                caller.msg("Ignore settings could not be saved. Please try again.")
                return
            if removed:
                caller.msg(f"No longer ignoring |w{target.key}|n.")
            else:
                caller.msg(f"{target.key} isn't on your list.")
            return
        level = (
            ignore.FULL
            if "full" in self.switches
            else (ignore.POSTS if "except" in self.switches else ignore.HIDDEN)
        )
        try:
            changed = ignore.set_entry(caller, target, level)
        except ignore.PolicyChangeError:
            caller.msg("Ignore settings could not be saved. Please try again.")
            return
        except ValueError as exc:
            caller.msg(str(exc))
            return
        if not changed:
            caller.msg(f"{target.key} already has that entry on your list.")
        elif level == ignore.POSTS:
            caller.msg(f"Showing posts from |w{target.key}|n; contact stays blocked.")
        elif level == ignore.FULL:
            caller.msg(f"Now ignoring |w{target.key}|n (full), including alts.")
        else:
            caller.msg(f"Now ignoring |w{target.key}|n. Their posts appear as muted placeholders.")

    def _view(self, caller, account):
        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        named, earlier = ignore.entries(account), ignore.earlier(account)
        if not named and not earlier:
            caller.msg("Your ignore list is empty.")
            return
        lines = ["|wIgnore List|n"]
        account_mode = comms_identity() == "account"
        for char_id, entry in named.items():
            target = ObjectDB.objects.filter(pk=char_id).first()
            name = target.key if target else entry["name"]
            label = {ignore.FULL: " (full)", ignore.POSTS: " (except)"}.get(entry["level"], "")
            if account_mode:
                accounts = AccountDB.objects.filter(pk__in=entry["accounts"])
                label += " — " + ", ".join(a.key for a in accounts)
            lines.append(f"  {name}{label}")
        if earlier:
            lines.append(f"  {len(earlier)} earlier full ignores, made before names were recorded")
            if account_mode:
                lines.extend(f"    {a.key}" for a in AccountDB.objects.filter(pk__in=earlier))
        lines.append("Use +ignore/remove <character> or +ignore/clear to remove entries.")
        caller.msg("\n".join(lines))
