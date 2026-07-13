# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Character and Room mixins for the pose pipeline.

Mix ``PosingCharacterMixin`` into your Character typeclass and
``PosingRoomMixin`` into your Room typeclass. Both are plain Python mixins
with no Django models — they only add Evennia ``AttributeProperty`` state and
override hook methods, so mixing order relative to ``DefaultCharacter`` /
``DefaultRoom`` only needs the mixin to come first in the MRO::

    from evennia_posing import PosingCharacterMixin, PosingRoomMixin

    class Character(PosingCharacterMixin, DefaultCharacter):
        ...

    class Room(PosingRoomMixin, DefaultRoom):
        ...

If you also install ``evennia_social`` (which layers ignore-filtering onto
``msg()``), put it *before* ``PosingCharacterMixin`` so ignored content is
filtered before header/highlight processing runs::

    class Character(SocialCharacterMixin, PosingCharacterMixin,
                     ObjectParent, DefaultCharacter):
        ...

See README "Integration recipe" for the full wiring guide, including the
``pose_recorded`` signal and the account options this contrib expects the
game to register.
"""

import time

from evennia.typeclasses.attributes import AttributeProperty

from evennia_posing.highlighting import highlight_names
from evennia_posing.signals import pose_recorded


class PosingCharacterMixin:
    """Character mixin providing pose tracking, headers, and highlighting.

    Adds ``last_pose_time``, ``pose_status``, and ``last_pose_text`` state;
    a ``record_pose()`` entry point that other systems (or this contrib's own
    commands) call on every pose/say/emit; and a ``msg()`` override applying
    optional pose headers and name highlighting to incoming pose/say text.
    """

    # Unix timestamp of last pose/say/emit. Updated by record_pose().
    # Read by +pot and Room.get_characters_by_pose_time().
    last_pose_time = AttributeProperty(default=None, autocreate=False)
    # Current RP status: "ic", "observing", or "afk".
    pose_status = AttributeProperty(default="ic")
    # Full text of the character's most recent pose, for +lastpose.
    last_pose_text = AttributeProperty(default="", autocreate=False)

    # -----------------------------------------------------------------
    # Pose dispatch
    # -----------------------------------------------------------------

    def record_pose(self, pose_text, pose_type="pose"):
        """Central method for recording a pose, say, emit, or semipose.

        1. Updates the pose timestamp (for +pot ordering) and stored text
           (for +lastpose).
        2. Breaks observer mode if the character was observing — posing
           means you're participating now.
        3. Fires the ``pose_recorded`` signal so other systems (scene
           logging, RP session tracking, XP collection, ...) can react.
           See README for the recommended single-listener wiring pattern.

        Args:
            pose_text (str): The full text of the pose.
            pose_type (str): One of "pose", "emit", "say" (semipose calls
                this with pose_type="pose" — see CmdSemipose).
        """
        self.last_pose_time = time.time()
        self.last_pose_text = pose_text

        if self.pose_status == "observing":
            self.pose_status = "ic"

        pose_recorded.send(
            sender=self.__class__,
            character=self,
            pose_text=pose_text,
            pose_type=pose_type,
            location=self.location,
        )

    # -----------------------------------------------------------------
    # Hook overrides
    # -----------------------------------------------------------------

    def at_say(
        self,
        message,
        msg_self=None,
        msg_location=None,
        receivers=None,
        msg_receivers=None,
        **kwargs,
    ):
        """Hook called by CmdSay/CmdWhisper. Extends with pose tracking.

        Evennia's CmdSay delegates all formatting and delivery to this
        method. We call super() to handle messaging, then record the say
        for +pot and +lastpose — but only for room-visible says, not
        whispers (which have explicit receivers).
        """
        super().at_say(
            message,
            msg_self=msg_self,
            msg_location=msg_location,
            receivers=receivers,
            msg_receivers=msg_receivers,
            **kwargs,
        )
        if not receivers:
            self.record_pose(message, pose_type="say")

    def at_post_move(self, source_location, move_type="move", **kwargs):
        """Called after a successful move.

        Extends DefaultCharacter's auto-look with a pose timer reset.
        Entering a room marks you as "just arrived" in +pot.
        """
        super().at_post_move(source_location, move_type=move_type, **kwargs)
        self.last_pose_time = time.time()
        self.last_pose_text = ""

    def at_post_puppet(self, **kwargs):
        """Called after an Account puppets this Character.

        Resets the pose timer and sets status to IC on login.
        """
        super().at_post_puppet(**kwargs)
        self.last_pose_time = time.time()
        self.pose_status = "ic"

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        """Called after an Account unpuppets this Character.

        Clears the pose timer so disconnected characters don't show stale
        times in +pot.
        """
        super().at_post_unpuppet(account=account, session=session, **kwargs)
        self.last_pose_time = None

    def msg(self, text=None, from_obj=None, session=None, options=None, **kwargs):
        """Apply pose headers and name highlighting to incoming pose/say text.

        Processing order:
        1. Pose headers — prepend a configurable header showing the poser's
           name above their pose/say (skipped for say self-echoes).
        2. Name highlighting — colorize character names in the text.

        Both are gated on account options (``show_pose_headers``,
        ``highlight_enabled``, etc. — see README) and are no-ops if the
        receiver has no account or the relevant option is off.
        """
        if text and from_obj and self.account:
            if isinstance(text, tuple) and len(text) >= 2:
                msg_text, msg_opts = text[0], text[1]
            else:
                msg_text, msg_opts = None, {}

            msg_type = msg_opts.get("type", "")

            if msg_text and msg_type in ("pose", "say"):
                should_header = True
                if msg_type == "say" and from_obj == self:
                    should_header = False

                if should_header and self.account.options.get("show_pose_headers", True):
                    poser_name = from_obj.get_display_name(looker=self)
                    fmt = self.account.options.get("pose_header_format", "--- {name} ---")
                    header = fmt.format(name=poser_name)

                    separator = self.account.options.get("pose_separator", "")
                    prefix = f"{separator}\n{header}" if separator else header

                    msg_text = f"{prefix}\n{msg_text}"

                if self.location and self.account.options.get("highlight_enabled", True):
                    characters = [
                        obj for obj in self.location.contents if hasattr(obj, "last_pose_time")
                    ]
                    msg_text = highlight_names(msg_text, self, characters)

                text = (msg_text, msg_opts)

        super().msg(text=text, from_obj=from_obj, session=session, options=options, **kwargs)


class PosingRoomMixin:
    """Room mixin providing pose-order sorting and display integration.

    Adds ``get_characters_by_pose_time()`` (used by +pot and +lastpose),
    a pose-sorted, OBS/AFK-annotated character listing in room appearance,
    and name highlighting in the room's formatted output.
    """

    def get_characters_by_pose_time(self):
        """Return characters in this room sorted by last_pose_time ascending.

        Characters who have waited longest to pose appear first (for +pot).
        Characters with no pose time (None) sort first as "just arrived."
        Only puppeted (player) characters are included.

        Returns:
            list: Character objects sorted by pose time.
        """
        characters = [
            obj for obj in self.contents if obj.has_account and hasattr(obj, "last_pose_time")
        ]
        characters.sort(key=lambda c: c.last_pose_time or 0)
        return characters

    def get_display_characters(self, looker, **kwargs):
        """Get the character listing for room appearance.

        Characters are sorted by pose time (longest-waiting first) and
        annotated with their pose status (Observing/AFK).
        """
        characters = [
            obj
            for obj in self.contents_get(content_type="character")
            if obj != looker and obj.access(looker, "view")
        ]
        if not characters:
            return ""

        characters.sort(key=lambda c: getattr(c, "last_pose_time", None) or 0)

        char_lines = []
        for char in characters:
            name = char.get_display_name(looker, **kwargs)

            status = getattr(char, "pose_status", "ic")
            if status == "observing":
                name = f"{name} |w[OBS]|n"
            elif status == "afk":
                name = f"{name} |x[AFK]|n"

            char_lines.append(f"  {name}")

        return "|wCharacters:|n\n" + "\n".join(char_lines)

    def format_appearance(self, appearance, looker, **kwargs):
        """Final processing of room appearance string.

        Applies name highlighting: the looker's own name is highlighted in
        their self-color, other visible character names in the others-color.
        Preferences are read from the looker's Account OptionHandler.
        """
        appearance = super().format_appearance(appearance, looker, **kwargs)

        account = getattr(looker, "account", None)
        if account and account.options.get("highlight_enabled", True):
            characters = [obj for obj in self.contents if hasattr(obj, "last_pose_time")]
            appearance = highlight_names(appearance, looker, characters)

        return appearance
