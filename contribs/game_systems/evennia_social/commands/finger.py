# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Character profile viewing and editing — +finger command.

Provides CmdFinger for viewing/editing character profiles: identity
fields, bio, custom fields, and theme following.

Uses plain EvEditor callbacks (not a version-tracked editing framework) —
bios are personal text, not collaborative content.
"""

from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

from evennia_social.social import is_staff

# ---------------------------------------------------------------------------
# EvEditor callbacks for +finger/edit (bio editing)
# ---------------------------------------------------------------------------


def _finger_load(caller):
    """Load the character's bio into the editor."""
    return caller.profile_bio or ""


def _finger_save(caller, buffer):
    """Save the editor buffer as the character's bio."""
    caller.profile_bio = buffer.strip()
    caller.msg("|gBio saved.|n")
    return True


def _finger_quit(caller):
    """Clean up when the editor is exited."""
    caller.msg("Bio editor closed.")


# ---------------------------------------------------------------------------
# Field mapping for /set and /clear
# ---------------------------------------------------------------------------

# Always-present fields reset to "Unspecified" on /clear.
_IDENTITY_FIELDS = {
    "gender": "profile_gender",
    "ancestry": "profile_ancestry",
    "homeland": "profile_homeland",
    "role": "profile_role",
    "pronouns": "profile_pronouns",
}

# Optional fields cleared to "" on /clear.
_OPTIONAL_FIELDS = {
    "quote": "profile_quote",
    "rpprefs": "profile_rp_prefs",
    "rp": "profile_rp_prefs",
    "prefs": "profile_rp_prefs",
    "sdesc": "short_desc",
    "short_desc": "short_desc",
}

_ALL_SETTABLE = {**_IDENTITY_FIELDS, **_OPTIONAL_FIELDS}

# bio is only editable via /edit, clearable via /clear
_CLEARABLE_EXTRAS = {"bio": "profile_bio"}

_MAX_CUSTOM_FIELDS = 10
_MAX_FOLLOWED_THEMES = 20


# ---------------------------------------------------------------------------
# CmdFinger
# ---------------------------------------------------------------------------


class CmdFinger(MuxCommand):
    """
    View or edit a character's profile.

    Usage:
        +finger [<character>]             - View a profile (own if no arg)
        +finger/set <field>=<value>       - Set a profile field
        +finger/clear <field>             - Clear/reset a profile field
        +finger/edit                      - Open bio editor
        +finger/custom <key>=<value>      - Set a custom field (max 10)
        +finger/custom <key>              - Clear a custom field
        +finger/themes [<character>]      - View followed themes in detail
        +finger/follow <theme>[=<detail>] - Follow a theme/tag
        +finger/unfollow <theme>          - Stop following a theme/tag
        +finger/public <theme>            - Toggle a theme's public visibility

    Settable fields: gender, ancestry, homeland, role, pronouns,
        quote, rpprefs, sdesc

    Identity fields (gender, ancestry, homeland, role, pronouns) reset
    to "Unspecified" when cleared. Other fields are removed entirely.
    """

    key = "+finger"
    aliases = ["+profile"]  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller

        if not self.switches:
            # View mode: own profile or another character's
            if self.args.strip():
                target = caller.search(self.args.strip())
                if not target:
                    return
            else:
                target = caller
            caller.msg(self._format_profile(caller, target))
            return

        switch = self.switches[0].lower()

        if switch == "set":
            self._do_set()
        elif switch == "clear":
            self._do_clear()
        elif switch == "edit":
            self._do_edit()
        elif switch == "custom":
            self._do_custom()
        elif switch == "themes":
            self._do_themes()
        elif switch == "follow":
            self._do_follow()
        elif switch == "unfollow":
            self._do_unfollow()
        elif switch == "public":
            self._do_public()
        else:
            self.caller.msg(f"|rUnknown switch:|n /{switch}. See |whelp +finger|n for usage.")

    @staticmethod
    def _format_profile(viewer, target):
        """Build the +finger display string for *target* as seen by *viewer*."""
        width = 72
        header = f" {target.key}'s Profile "
        lines = []

        # Header bar
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        # Name (with short_desc via get_display_name)
        display_name = target.get_display_name(looker=viewer)
        lines.append(f" |wName:|n        {display_name}")

        # Quote (only if set)
        if target.profile_quote:
            lines.append(f' |wQuote:|n       "{target.profile_quote}"')

        lines.append("")

        # Identity block (always shown)
        gender = target.profile_gender or "Unspecified"
        pronouns = target.profile_pronouns or "Unspecified"
        ancestry = target.profile_ancestry or "Unspecified"
        homeland = target.profile_homeland or "Unspecified"
        role = target.profile_role or "Unspecified"
        lines.append(f" |wGender:|n      {gender:<14}|wPronouns:|n  {pronouns}")
        lines.append(f" |wAncestry:|n    {ancestry:<14}|wHomeland:|n  {homeland}")
        lines.append(f" |wRole:|n        {role}")

        # RP Prefs (only if set)
        if target.profile_rp_prefs:
            lines.append(f" |wRP Prefs:|n    {target.profile_rp_prefs}")

        # Public followed themes (abbreviated)
        if target.followed_themes:
            public_themes = [
                name for name, meta in target.followed_themes.items() if meta.get("public", False)
            ]
            if public_themes:
                lines.append(f"|w{'-' * width}|n")
                lines.append(f" |wThemes:|n      {', '.join(sorted(public_themes))}")

        # Bio (only if set)
        if target.profile_bio:
            lines.append(f"|w{'-' * width}|n")
            lines.append(" |wAbout:|n")
            for bio_line in target.profile_bio.splitlines():
                lines.append(f" {bio_line}")

        # Custom fields (only if any)
        if target.profile_custom_fields:
            lines.append(f"|w{'-' * width}|n")
            for key, value in target.profile_custom_fields.items():
                lines.append(f" |w{key}:|n  {value}")

        # Staff section (Builder+ only)
        if is_staff(viewer):
            lines.append(f"|w{'-' * width}|n")
            lines.append(" |r[Staff Info]|n")
            account_name = target.account.key if target.account else "N/A"
            lines.append(f" |wAccount:|n     {account_name}")
            sessions = (
                target.sessions.all() if hasattr(target.sessions, "all") else target.sessions.get()
            )
            if sessions:
                lines.append(f" |wConnected:|n   Yes ({len(sessions)} session(s))")
            else:
                lines.append(" |wConnected:|n   No")

        # Footer
        lines.append(f"|w+{'=' * (width - 2)}+|n")

        return "\n".join(lines)

    @staticmethod
    def _format_themes(viewer, target):
        """Build the +finger/themes detail view."""
        width = 72
        is_self = viewer == target

        themes = target.followed_themes or {}
        if not themes:
            return f"{target.key} has no followed themes."

        header = f" {target.key}'s Followed Themes "
        lines = []
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        for name in sorted(themes.keys()):
            meta = themes[name]
            is_public = meta.get("public", False)
            detail = meta.get("detail", "")

            # Others only see public themes
            if not is_self and not is_public:
                continue

            visibility = "public" if is_public else "private"
            lines.append(f" |w{name}|n ({visibility})")
            if detail:
                lines.append(f'   "{detail}"')
            else:
                lines.append("   (no detail)")

        lines.append(f"|w+{'=' * (width - 2)}+|n")
        return "\n".join(lines)

    def _do_set(self):
        """Handle +finger/set <field>=<value>."""
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: |w+finger/set <field>=<value>|n")
            return

        field_name = self.lhs.strip().lower()
        value = self.rhs.strip()

        attr_name = _ALL_SETTABLE.get(field_name)
        if not attr_name:
            valid = ", ".join(sorted(_ALL_SETTABLE.keys()))
            self.caller.msg(f"|rUnknown field:|n {field_name}. Valid fields: {valid}")
            return

        setattr(self.caller, attr_name, value)
        self.caller.msg(f"|g{field_name.capitalize()}|n set to: {value}")

    def _do_clear(self):
        """Handle +finger/clear <field>."""
        if not self.args.strip():
            self.caller.msg("Usage: |w+finger/clear <field>|n")
            return

        field_name = self.args.strip().lower()

        # Check identity fields first (reset to "Unspecified")
        attr_name = _IDENTITY_FIELDS.get(field_name)
        if attr_name:
            setattr(self.caller, attr_name, "Unspecified")
            self.caller.msg(f"|g{field_name.capitalize()}|n reset to Unspecified.")
            return

        # Check optional fields (clear to "")
        attr_name = _OPTIONAL_FIELDS.get(field_name)
        if not attr_name:
            attr_name = _CLEARABLE_EXTRAS.get(field_name)
        if attr_name:
            setattr(self.caller, attr_name, "")
            self.caller.msg(f"|g{field_name.capitalize()}|n cleared.")
            return

        valid = ", ".join(
            sorted(
                set(_IDENTITY_FIELDS.keys())
                | set(_OPTIONAL_FIELDS.keys())
                | set(_CLEARABLE_EXTRAS.keys())
            )
        )
        self.caller.msg(f"|rUnknown field:|n {field_name}. Valid fields: {valid}")

    def _do_edit(self):
        """Handle +finger/edit — open EvEditor for bio."""
        EvEditor(
            self.caller,
            loadfunc=_finger_load,
            savefunc=_finger_save,
            quitfunc=_finger_quit,
            key="profile bio",
        )

    def _do_custom(self):
        """Handle +finger/custom <key>[=<value>]."""
        if not self.args.strip():
            self.caller.msg("Usage: |w+finger/custom <key>=<value>|n")
            return

        caller = self.caller

        if self.rhs is not None:
            # Set a custom field
            key = self.lhs.strip()
            value = self.rhs.strip()
            if not key:
                caller.msg("Usage: |w+finger/custom <key>=<value>|n")
                return

            fields = caller.profile_custom_fields or {}
            if key not in fields and len(fields) >= _MAX_CUSTOM_FIELDS:
                caller.msg(f"|rCustom field limit reached|n (max {_MAX_CUSTOM_FIELDS}).")
                return

            fields[key] = value
            caller.profile_custom_fields = fields
            caller.msg(f"Custom field |w{key}|n set to: {value}")
        else:
            # Clear a custom field
            key = self.args.strip()
            fields = caller.profile_custom_fields or {}
            if key not in fields:
                caller.msg(f"No custom field named |w{key}|n.")
                return

            del fields[key]
            caller.profile_custom_fields = fields if fields else None
            caller.msg(f"Custom field |w{key}|n removed.")

    def _do_themes(self):
        """Handle +finger/themes [<name>]."""
        if self.args.strip():
            target = self.caller.search(self.args.strip())
            if not target:
                return
        else:
            target = self.caller
        self.caller.msg(self._format_themes(self.caller, target))

    def _do_follow(self):
        """Handle +finger/follow <theme>[=<detail>]."""
        caller = self.caller
        theme = self.lhs.strip() if self.lhs else self.args.strip()
        detail = self.rhs.strip() if self.rhs else ""

        if not theme:
            caller.msg("Usage: |w+finger/follow <theme>[=<detail>]|n")
            return

        themes = caller.followed_themes or {}
        if theme not in themes and len(themes) >= _MAX_FOLLOWED_THEMES:
            caller.msg(f"|rFollowed theme limit reached|n (max {_MAX_FOLLOWED_THEMES}).")
            return

        existing = themes.get(theme, {})
        themes[theme] = {
            "public": existing.get("public", False),
            "detail": detail if detail else existing.get("detail", ""),
        }
        caller.followed_themes = themes
        if detail:
            caller.msg(f"Now following |w{theme}|n with detail: {detail}")
        else:
            caller.msg(f"Now following |w{theme}|n.")

    def _do_unfollow(self):
        """Handle +finger/unfollow <theme>."""
        caller = self.caller
        theme = self.args.strip()
        if not theme:
            caller.msg("Usage: |w+finger/unfollow <theme>|n")
            return

        themes = caller.followed_themes or {}
        if theme not in themes:
            caller.msg(f"You are not following |w{theme}|n.")
            return

        del themes[theme]
        caller.followed_themes = themes if themes else None
        caller.msg(f"Stopped following |w{theme}|n.")

    def _do_public(self):
        """Handle +finger/public <theme> — toggle public visibility."""
        caller = self.caller
        theme = self.args.strip()
        if not theme:
            caller.msg("Usage: |w+finger/public <theme>|n")
            return

        themes = caller.followed_themes or {}
        if theme not in themes:
            caller.msg(f"You are not following |w{theme}|n.")
            return

        meta = themes[theme]
        meta["public"] = not meta.get("public", False)
        themes[theme] = meta
        caller.followed_themes = themes
        state = "public" if meta["public"] else "private"
        caller.msg(f"|w{theme}|n is now |w{state}|n.")
