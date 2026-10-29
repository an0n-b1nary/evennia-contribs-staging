# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Shared test scaffolding for evennia_social.

Composes SocialCharacterMixin + PosingCharacterMixin (and the Room
equivalents) into local test typeclasses, in the MRO order this contrib's
README requires (social before posing), since the stock Evennia
DefaultCharacter/DefaultRoom used by EvenniaTest don't carry either
contrib's state.

Account options both contribs need are registered for each test class,
mirroring the registration step a consuming game performs (see both READMEs'
"Register the account options" steps), so this contrib's own suite is
self-contained. A host that runs these tests keeps its own definitions, and
later test classes see its settings unchanged.
"""

from django.conf import settings
from django.test import override_settings
from evennia.objects.objects import DefaultCharacter, DefaultRoom
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_posing.typeclasses import PosingCharacterMixin, PosingRoomMixin
from evennia_social.typeclasses import SocialCharacterMixin, SocialRoomMixin

_ACCOUNT_OPTIONS = {
    "show_pose_headers": ("Show character name headers above poses.", "Boolean", True),
    "pose_header_format": (
        "Format string for pose headers.",
        "Text",
        "--- {name} ---",
    ),
    "pose_separator": ("Visual separator between poses.", "Text", ""),
    "highlight_enabled": (
        "Highlight character names in poses and room descriptions.",
        "Boolean",
        True,
    ),
    "highlight_self_color": ("Color for your own name in poses.", "Color", "w"),
    "highlight_others_color": ("Color for other character names.", "Color", "c"),
}


def _register_account_options(cls):
    """Apply _ACCOUNT_OPTIONS for one test class; host definitions win."""
    cls.enterClassContext(
        override_settings(
            OPTIONS_ACCOUNT_DEFAULT={**_ACCOUNT_OPTIONS, **settings.OPTIONS_ACCOUNT_DEFAULT}
        )
    )


class SocialTestCharacter(SocialCharacterMixin, PosingCharacterMixin, DefaultCharacter):
    """Test-local Character mixing social (first) + posing (second)."""


class SocialTestRoom(SocialRoomMixin, PosingRoomMixin, DefaultRoom):
    """Test-local Room mixing social + posing."""


class SocialTestCase(EvenniaTest):
    """Base test case: composed typeclasses + registered account options."""

    character_typeclass = SocialTestCharacter
    room_typeclass = SocialTestRoom

    @classmethod
    def setUpClass(cls):
        _register_account_options(cls)
        super().setUpClass()


class SocialCommandTestCase(EvenniaCommandTest):
    """Base command test case: composed typeclasses + registered account options."""

    character_typeclass = SocialTestCharacter
    room_typeclass = SocialTestRoom

    @classmethod
    def setUpClass(cls):
        _register_account_options(cls)
        super().setUpClass()
