# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Character and Room mixins for the social QoL layer.

Mix ``SocialCharacterMixin`` into your Character typeclass and
``SocialRoomMixin`` into your Room typeclass::

    from evennia_social import SocialCharacterMixin, SocialRoomMixin

    class Character(SocialCharacterMixin, DefaultCharacter):
        ...

    class Room(SocialRoomMixin, DefaultRoom):
        ...

This contrib hard-depends on ``evennia_posing`` (see pyproject.toml) and is
designed to be layered *on top* of it. If you also install
``evennia_posing``, put ``SocialCharacterMixin``/``SocialRoomMixin`` *before*
``PosingCharacterMixin``/``PosingRoomMixin`` in your MRO so ignore-filtering
runs before header/highlight processing::

    class Character(SocialCharacterMixin, PosingCharacterMixin,
                     ObjectParent, DefaultCharacter):
        ...

See README "Integration recipe" for the full wiring guide.
"""

from evennia.typeclasses.attributes import AttributeProperty

# Predefined hangout types for +hangouts directory.
HANGOUT_TYPES = (
    "bar",
    "eatery",
    "arena",
    "market",
    "park",
    "temple",
    "library",
    "plaza",
    "theater",
    "docks",
)


def _ignore_placeholder(msg_type):
    """Return a partial-visibility placeholder for an ignored player's message.

    Used by SocialCharacterMixin.msg() to replace content from ignored
    players with a muted indicator that preserves conversational context
    without exposing the actual content.
    """
    if msg_type == "say":
        return "|x[An ignored player said something.]|n"
    return "|x[An ignored player posed.]|n"


class SocialCharacterMixin:
    """Character mixin providing profile, page, ignore, summon/join, and
    home-room state, plus the ignore-filtering half of the cooperative
    ``msg()`` chain.
    """

    # -- Visited rooms (feeds @tel's "visited" teleport mode) --
    visited_rooms = AttributeProperty(default=None, autocreate=False)

    # -- Short description shown in room listings via get_display_name() --
    short_desc = AttributeProperty(default="", autocreate=False)

    # -- Profile: always-present identity fields --
    profile_gender = AttributeProperty(default="Unspecified", autocreate=False)
    profile_ancestry = AttributeProperty(default="Unspecified", autocreate=False)
    profile_homeland = AttributeProperty(default="Unspecified", autocreate=False)
    profile_role = AttributeProperty(default="Unspecified", autocreate=False)
    profile_pronouns = AttributeProperty(default="Unspecified", autocreate=False)

    # -- Profile: optional fields --
    profile_bio = AttributeProperty(default="", autocreate=False)
    profile_quote = AttributeProperty(default="", autocreate=False)
    profile_rp_prefs = AttributeProperty(default="", autocreate=False)
    profile_custom_fields = AttributeProperty(default=None, autocreate=False)

    # -- Followed themes/tags: {name: {"public": bool, "detail": str}} --
    followed_themes = AttributeProperty(default=None, autocreate=False)

    # -- Page / +msg --
    last_pager = AttributeProperty(default=None, autocreate=False)
    last_page_seen = AttributeProperty(default=None, autocreate=False)

    # -- Summon / join --
    # {requester_char_id: {"type": "summon"|"join", "room_id": int, "timestamp": str}}
    pending_summon_requests = AttributeProperty(default=None, autocreate=False)

    # -- Home room --
    home_room = AttributeProperty(default=None, autocreate=False)

    # -----------------------------------------------------------------
    # Visit tracking
    # -----------------------------------------------------------------

    def _record_visit(self):
        """Record current location in visited_rooms for @tel access."""
        if self.location:
            if self.visited_rooms is None:
                self.visited_rooms = set()
            visited = self.visited_rooms
            visited.add(self.location.dbref)
            self.visited_rooms = visited  # trigger Attribute save

    # -----------------------------------------------------------------
    # Hook overrides
    # -----------------------------------------------------------------

    def at_post_move(self, source_location, move_type="move", **kwargs):
        """Called after a successful move. Records the visit for @tel."""
        super().at_post_move(source_location, move_type=move_type, **kwargs)
        self._record_visit()

    def at_post_puppet(self, **kwargs):
        """Called after an Account puppets this Character.

        Records the current room as visited and notifies about unread
        pages received while offline.
        """
        super().at_post_puppet(**kwargs)
        self._record_visit()
        self._notify_unread_pages()

    def _notify_unread_pages(self):
        """Check for pages received while offline and notify the player."""
        from datetime import UTC, datetime

        from django.db.models import Q
        from evennia.comms.models import Msg

        page_filter = Q(db_tags__db_key__iexact="page", db_tags__db_category__iexact="comms")
        pages = Msg.objects.get_messages_by_receiver(self).filter(page_filter)
        if self.last_page_seen:
            # last_page_seen is stored as an ISO 8601 string for Django
            # DateTimeField compatibility.
            cutoff = datetime.fromisoformat(self.last_page_seen)
            pages = pages.filter(db_date_created__gt=cutoff)
        count = pages.count()
        if count > 0:
            plural = "s" if count != 1 else ""
            self.msg(
                f"|wYou have {count} unread page{plural}.|n Use |wpage/last {count}|n to view."
            )
        self.last_page_seen = datetime.now(UTC).isoformat()

    def msg(self, text=None, from_obj=None, session=None, options=None, **kwargs):
        """Filter content from ignored players before it reaches the
        pose-header/highlight processing done by PosingCharacterMixin (or
        any other mixin layered below this one).

        Staff (Builder+) senders bypass ignore filters. Whispers and pages
        from ignored players are suppressed entirely; poses/says are
        replaced with a muted placeholder that preserves conversational
        context without exposing the content.
        """
        if text and from_obj and self.account and from_obj != self:
            if isinstance(text, tuple) and len(text) >= 2:
                msg_text, msg_opts = text[0], text[1]
            else:
                msg_text, msg_opts = None, {}

            msg_type = msg_opts.get("type", "")

            if msg_text and msg_type in ("pose", "say", "whisper", "page", "ooc"):
                from_acct = getattr(from_obj, "account", None)
                if from_acct:
                    ignore_list = self.account.db.ignore_list or []
                    is_staff_sender = from_acct.check_permstring("Builder")
                    if from_acct.id in ignore_list and not is_staff_sender:
                        if msg_type in ("whisper", "page"):
                            return  # full suppression
                        placeholder = _ignore_placeholder(msg_type)
                        # Retag as "system": the placeholder is no longer
                        # real pose/say content, and passing the original
                        # "pose"/"say" type through would let a downstream
                        # mixin's msg() (e.g. PosingCharacterMixin) apply
                        # pose headers/highlighting to the muted notice.
                        text = (placeholder, {**msg_opts, "type": "system"})
                        super().msg(
                            text=text,
                            from_obj=from_obj,
                            session=session,
                            options=options,
                            **kwargs,
                        )
                        return

        super().msg(text=text, from_obj=from_obj, session=session, options=options, **kwargs)

    def get_display_name(self, looker=None, **kwargs):
        """Returns the character's display name, with short_desc if set.

        Format: "Name - short description"
        e.g., "Korben - a tall man in a red cloak"
        """
        name = super().get_display_name(looker=looker, **kwargs)
        if self.short_desc:
            name = f"{name} - {self.short_desc}"
        return name


class SocialRoomMixin:
    """Room mixin providing hangout-directory designation and per-room
    teleport access control.
    """

    # -- Hangout designation: one of HANGOUT_TYPES, or None --
    hangout_type = AttributeProperty(default=None, autocreate=False)

    # -- Teleport access: "public", "private", or "secret" --
    allow_teleport = AttributeProperty(default="public")
