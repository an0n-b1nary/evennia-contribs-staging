# SPDX-License-Identifier: BSD-3-Clause
"""Identity policy and deferred host configuration validation."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.checks import Tags, run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from evennia import CmdSet, Command
from evennia.accounts.accounts import DefaultAccount, DefaultGuest
from evennia.utils.create import create_account
from evennia.utils.test_resources import EvenniaTest

from evennia_links.guests import GuestAccountMixin
from evennia_links.guests import is_visitor as guest_is_visitor
from evennia_links.identity import (
    CharacterCommsAccountMixin,
    check_comms_identity,
    comms_identity,
    comms_identity_system_check,
    is_visitor,
)


class PrivateAccount(CharacterCommsAccountMixin, DefaultAccount):
    pass


class PrivateGuest(CharacterCommsAccountMixin, GuestAccountMixin, DefaultGuest):
    pass


class CharacterChannel:
    # PR 3 supplies the channel implementation; this fixture exercises its
    # marker contract without introducing channel behavior in the foundation.
    comms_identity = "character"


class AccountCommand(Command):
    key = "account-command"
    comms_identity = "account"


class CharacterCommand(Command):
    key = "character-command"
    comms_identity = "character"


class AccountCommands(CmdSet):
    def at_cmdset_creation(self):
        self.add(AccountCommand())


class CharacterCommands(CmdSet):
    def at_cmdset_creation(self):
        self.add(CharacterCommand())


class MixedCommands(CmdSet):
    def at_cmdset_creation(self):
        self.add(AccountCommand())
        self.add(CharacterCommand())


class WrongOrderGuest(GuestAccountMixin, CharacterCommsAccountMixin, DefaultGuest):
    pass


class BrokenCommands(CmdSet):
    def at_cmdset_creation(self):
        raise ValueError("broken composition")


def path(cls):
    return f"{cls.__module__}.{cls.__name__}"


@override_settings(EVENNIA_COMMS_IDENTITY="character")
class TestVisitorIdentity(EvenniaTest):
    def test_visitor_matrix_in_both_modes(self):
        self.account.permissions.clear()
        self.account.is_superuser = False
        guest = create_account("IdentityGuest", None, "test-password", typeclass=DefaultGuest)
        guest.characters.add(self.char2)
        with patch.object(self.account, "get_all_puppets", return_value=[]):
            for mode in ("account", "character"):
                with self.settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                    self.assertFalse(is_visitor(None))
                    self.assertTrue(is_visitor(guest))
                    self.assertTrue(is_visitor(self.char2))
                    self.assertFalse(is_visitor(self.char1))
                    self.assertEqual(is_visitor(self.account), mode == "character")
                    self.assertEqual(
                        is_visitor(self.account, SimpleNamespace(puppet=None)), mode == "character"
                    )
                    self.assertFalse(is_visitor(self.account, SimpleNamespace(puppet=self.char1)))

    def test_session_without_puppet_is_visitor_even_with_another_live_session(self):
        self.account.permissions.clear()
        self.account.is_superuser = False
        with patch.object(self.account, "get_all_puppets", return_value=[self.char1, self.char2]):
            self.assertFalse(is_visitor(self.account))
            self.assertTrue(is_visitor(self.account, SimpleNamespace(puppet=None)))
            self.assertFalse(is_visitor(self.account, SimpleNamespace(puppet=self.char1)))

    def test_staff_without_puppet_are_not_visitors(self):
        self.account.permissions.clear()
        for superuser, permission in ((True, None), (False, "Builder"), (False, "Admin")):
            with self.subTest(superuser=superuser, permission=permission):
                self.account.is_superuser = superuser
                self.account.permissions.clear()
                if permission:
                    self.account.permissions.add(permission)
                self.assertFalse(is_visitor(self.account, SimpleNamespace(puppet=None)))

    def test_single_puppet_without_explicit_session(self):
        self.account.permissions.clear()
        self.account.is_superuser = False
        with patch.object(self.account, "get_all_puppets", return_value=[self.char1]):
            self.assertFalse(is_visitor(self.account))

    def test_guests_reexport_the_same_policy(self):
        self.assertIs(guest_is_visitor, is_visitor)


class TestAccountDisplay(EvenniaTest):
    account_typeclass = PrivateAccount

    def setUp(self):
        super().setUp()
        self.account2.permissions.clear()
        self.account2.is_superuser = False

    def test_stranger_and_anonymous_viewers_get_neutral_name(self):
        for looker in (None, self.account2, self.char2, AnonymousUser()):
            with self.subTest(looker=looker):
                self.assertEqual(self.account.get_display_name(looker), "Newcomer")

    def test_self_and_owned_characters_retain_account_name(self):
        self.account.characters.add(self.char1)
        for looker in (self.account, self.char1):
            with self.subTest(looker=looker):
                self.assertIn(self.account.key, self.account.get_display_name(looker))
        self.char1.account = None
        self.assertIn(self.account.key, self.account.get_display_name(self.char1))

    def test_staff_accounts_and_their_characters_see_real_name(self):
        self.account2.permissions.add("Builder")
        for looker in (self.account2, self.char2):
            with self.subTest(looker=looker):
                self.assertIn(self.account.key, self.account.get_display_name(looker))
        self.account2.permissions.clear()
        self.account2.is_superuser = True
        self.assertIn(self.account.key, self.account.get_display_name(self.account2))

    @override_settings(GUEST_ACCOUNT_CMDSET="evennia.commands.cmdset.CmdSet")
    def test_guest_suffix_does_not_expose_account_to_players(self):
        guest = create_account("PrivateGuestName", None, "test-password", typeclass=PrivateGuest)
        self.assertEqual(guest.get_display_name(self.account2), "Newcomer")
        self.assertEqual(guest.get_display_name(None), "Newcomer")
        self.assertIn("PrivateGuestName", guest.get_display_name(guest))
        self.assertIn("(guest)", guest.get_display_name(guest))


@override_settings(
    EVENNIA_COMMS_IDENTITY="account",
    BASE_ACCOUNT_TYPECLASS=path(DefaultAccount),
    BASE_GUEST_TYPECLASS=path(DefaultGuest),
    BASE_CHANNEL_TYPECLASS="evennia.comms.comms.DefaultChannel",
    CMDSET_ACCOUNT=path(CmdSet),
    CMDSET_CHARACTER=path(CmdSet),
    GUEST_ACCOUNT_CMDSET=path(CmdSet),
    GUEST_CHARACTER_CMDSET=path(CmdSet),
)
class TestIdentityConfiguration(SimpleTestCase):
    def character_settings(self, **kwargs):
        return self.settings(
            EVENNIA_COMMS_IDENTITY="character",
            BASE_ACCOUNT_TYPECLASS=path(PrivateAccount),
            BASE_GUEST_TYPECLASS=path(PrivateGuest),
            BASE_CHANNEL_TYPECLASS=path(CharacterChannel),
            **kwargs,
        )

    def test_default_and_invalid_setting_values(self):
        with patch("evennia_links.identity.settings", SimpleNamespace()):
            self.assertEqual(comms_identity(), "account")
        for value in (None, "", "characters", "Account", 1):
            with (
                self.settings(EVENNIA_COMMS_IDENTITY=value),
                self.subTest(value=value),
                self.assertRaisesMessage(ImproperlyConfigured, "EVENNIA_COMMS_IDENTITY"),
            ):
                comms_identity()

    def test_account_and_character_configurations_pass(self):
        self.assertIsNone(check_comms_identity())
        with self.settings(CMDSET_ACCOUNT=path(AccountCommands)):
            self.assertIsNone(check_comms_identity())
        with self.character_settings(CMDSET_CHARACTER=path(CharacterCommands)):
            self.assertIsNone(check_comms_identity())

    def test_each_cmdset_is_instantiated_and_checked_in_both_modes(self):
        for setting in (
            "CMDSET_ACCOUNT",
            "CMDSET_CHARACTER",
            "GUEST_ACCOUNT_CMDSET",
            "GUEST_CHARACTER_CMDSET",
        ):
            with self.subTest(setting=setting):
                with (
                    self.settings(**{setting: path(CharacterCommands)}),
                    self.assertRaisesMessage(ImproperlyConfigured, "CharacterCommand"),
                ):
                    check_comms_identity()
                with (
                    self.character_settings(**{setting: path(AccountCommands)}),
                    self.assertRaisesMessage(ImproperlyConfigured, "AccountCommand"),
                ):
                    check_comms_identity()

    def test_all_typeclass_mismatches_are_reported_together(self):
        with (
            self.settings(
                BASE_ACCOUNT_TYPECLASS=path(PrivateAccount),
                BASE_GUEST_TYPECLASS=path(PrivateGuest),
                BASE_CHANNEL_TYPECLASS=path(CharacterChannel),
            ),
            self.assertRaises(ImproperlyConfigured) as caught,
        ):
            check_comms_identity()
        for name in ("BASE_ACCOUNT_TYPECLASS", "BASE_GUEST_TYPECLASS", "BASE_CHANNEL_TYPECLASS"):
            self.assertIn(name, str(caught.exception))

    def test_character_mode_requires_both_account_mixins_and_channel_marker(self):
        with (
            self.settings(EVENNIA_COMMS_IDENTITY="character"),
            self.assertRaises(ImproperlyConfigured) as caught,
        ):
            check_comms_identity()
        for name in ("BASE_ACCOUNT_TYPECLASS", "BASE_GUEST_TYPECLASS", "BASE_CHANNEL_TYPECLASS"):
            self.assertIn(name, str(caught.exception))

    def test_mixed_commands_and_hidden_base_markers_are_rejected(self):
        with (
            self.settings(CMDSET_ACCOUNT=path(MixedCommands)),
            self.assertRaisesMessage(ImproperlyConfigured, "CharacterCommand"),
        ):
            check_comms_identity()
        with (
            patch.object(PrivateAccount, "comms_identity", "account"),
            self.settings(BASE_ACCOUNT_TYPECLASS=path(PrivateAccount)),
            self.assertRaisesMessage(ImproperlyConfigured, "CharacterCommsAccountMixin"),
        ):
            check_comms_identity()

    def test_display_mixin_order_is_checked(self):
        with (
            self.character_settings(),
            self.settings(BASE_GUEST_TYPECLASS=path(WrongOrderGuest)),
            self.assertRaisesMessage(ImproperlyConfigured, "must precede GuestAccountMixin"),
        ):
            check_comms_identity()

    def test_import_and_cmdset_creation_errors_are_configuration_errors(self):
        with (
            self.settings(BASE_ACCOUNT_TYPECLASS="missing.module.Account"),
            self.assertRaisesMessage(ImproperlyConfigured, "BASE_ACCOUNT_TYPECLASS"),
        ):
            check_comms_identity()
        with (
            self.settings(CMDSET_ACCOUNT=path(BrokenCommands)),
            self.assertRaisesMessage(ImproperlyConfigured, "broken composition"),
        ):
            check_comms_identity()

    def test_missing_required_class_is_rejected_but_guest_cmdsets_are_optional(self):
        with self.settings(GUEST_ACCOUNT_CMDSET=None, GUEST_CHARACTER_CMDSET=None):
            self.assertIsNone(check_comms_identity())
        with (
            self.settings(CMDSET_ACCOUNT=""),
            self.assertRaisesMessage(
                ImproperlyConfigured, "CMDSET_ACCOUNT: a class path is required"
            ),
        ):
            check_comms_identity()

    def test_django_check_is_registered_and_reports_the_startup_error(self):
        self.assertEqual(comms_identity_system_check(), [])
        with self.settings(EVENNIA_COMMS_IDENTITY="invalid"):
            errors = run_checks(tags=[Tags.compatibility])
        errors = [error for error in errors if error.id == "evennia_links.E001"]
        self.assertEqual(len(errors), 1)
        self.assertIn("EVENNIA_COMMS_IDENTITY", errors[0].msg)
