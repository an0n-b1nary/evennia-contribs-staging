# SPDX-License-Identifier: BSD-3-Clause
"""Guest character naming through the real account creation hook."""

import random
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from evennia.accounts.accounts import DefaultGuest
from evennia.objects.objects import DefaultCharacter
from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_links.guest_names import default_guest_name, guest_character_name
from evennia_links.guests import GuestAccountMixin, is_guest


class NamedGuest(GuestAccountMixin, DefaultGuest):
    pass


class NamedCharacter(DefaultCharacter):
    pass


def custom_name():
    return "Wandering Heron"


@override_settings(
    GUEST_ACCOUNT_CMDSET="evennia.commands.cmdset.CmdSet",
    GUEST_CHARACTER_CMDSET="evennia.commands.cmdset.CmdSet",
)
class TestGuestNames(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.room1.tags.add("wing", category="guest")
        self.room1.tags.add("start", category="guest")

    def test_seeded_default_generator(self):
        with patch("evennia_links.guest_names.random", random.Random(223)):
            self.assertEqual(default_guest_name(), "Merry Panda")

    @override_settings(EVENNIA_GUEST_NAME_GENERATOR=custom_name)
    def test_creation_names_and_tags_character_without_changing_account(self):
        guest = create_account("Guest3", None, "test-password", typeclass=NamedGuest)
        character, errors = guest.create_character()
        self.assertFalse(errors)
        self.assertEqual(character.key, "Wandering Heron")
        self.assertEqual(guest.key, "Guest3")
        self.assertEqual(character.location, self.room1)
        self.assertEqual(character.home, self.room1)
        self.assertTrue(is_guest(character))
        self.assertIn("(guest)", guest.get_display_name(self.account))
        self.assertIn(character, guest.characters.all())

    def test_case_insensitive_collision_retries_then_uses_next_name(self):
        self.char1.key = "wandering HERON"
        generator = Mock(side_effect=["Wandering Heron", "Quiet Otter"])
        with self.settings(EVENNIA_GUEST_NAME_GENERATOR=generator):
            self.assertEqual(guest_character_name(), "Quiet Otter")
        self.assertEqual(generator.call_count, 2)

    @override_settings(EVENNIA_GUEST_NAME_GENERATOR=custom_name)
    def test_numbering_checks_existing_suffixes_and_character_subclasses(self):
        self.char1.key = "wandering heron"
        create_object(NamedCharacter, key="Wandering Heron 2", location=self.room1)
        self.assertEqual(guest_character_name(), "Wandering Heron 3")

    def test_dotted_custom_generator(self):
        with self.settings(EVENNIA_GUEST_NAME_GENERATOR=f"{__name__}.custom_name"):
            self.assertEqual(guest_character_name(), "Wandering Heron")

    @override_settings(EVENNIA_GUEST_NAME_GENERATOR=custom_name)
    def test_noncharacter_names_do_not_consume_guest_names(self):
        self.obj1.key = "Wandering Heron"
        self.assertEqual(guest_character_name(), "Wandering Heron")

    @override_settings(EVENNIA_GUEST_NAME_GENERATOR=custom_name)
    def test_name_is_freed_when_guest_character_is_deleted(self):
        guest = create_account("Guest4", None, "test-password", typeclass=NamedGuest)
        character, errors = guest.create_character()
        self.assertFalse(errors)
        self.assertEqual(guest_character_name(), "Wandering Heron 2")
        guest.at_post_disconnect()
        self.assertFalse(type(character).objects.filter(pk=character.pk).exists())
        self.assertEqual(guest_character_name(), "Wandering Heron")

    def test_bad_generator_configuration_is_reported(self):
        for generator in ("missing.module.generator", 3, lambda: "", lambda: None):
            with (
                self.settings(EVENNIA_GUEST_NAME_GENERATOR=generator),
                self.subTest(generator=generator),
                self.assertRaisesMessage(ImproperlyConfigured, "EVENNIA_GUEST_NAME_GENERATOR"),
            ):
                guest_character_name()
