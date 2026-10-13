"""Guest identity and movement policy without a host's command composition."""

from unittest.mock import MagicMock, patch

from evennia import CmdSet, Command
from evennia.accounts.accounts import DefaultGuest
from evennia.objects.objects import DefaultCharacter
from evennia.utils.create import create_account
from evennia.utils.test_resources import EvenniaTest

from evennia_links import characters
from evennia_links.characters import is_playable
from evennia_links.guests import GuestCharacterMixin, is_guest


class TrialCharacter(GuestCharacterMixin, DefaultCharacter):
    pass


class TestGuestIdentity(EvenniaTest):
    character_typeclass = TrialCharacter

    def test_ordinary_account_and_nonmodel_user_are_not_guests(self):
        self.assertFalse(is_guest(self.account))
        self.assertFalse(is_guest(self.char1))
        self.assertFalse(is_guest(MagicMock()))

    def test_guest_membership_still_counts_as_guest_offline(self):
        guest = create_account("Trial", None, "trial-password-for-tests", typeclass=DefaultGuest)
        guest.characters.add(self.char1)
        self.char1.account = None
        self.assertTrue(is_guest(self.char1))
        self.assertFalse(is_playable(self.char1))

    def test_offline_guest_check_does_not_resweep_every_account(self):
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.char1.account = None
        self.char2.account = None
        with patch.object(
            characters, "playable_accounts", wraps=characters.playable_accounts
        ) as sweep:
            swept = list(characters.playable_characters())
        self.assertIn(self.char1, swept)
        self.assertEqual(sweep.call_count, 1)

    def test_tagged_guest_boundary_cannot_be_disabled_with_move_hooks(self):
        self.char1.tags.add("character", category="guest")
        self.assertFalse(self.char1.move_to(self.room2, move_hooks=False))
        self.room2.tags.add("wing", category="guest")
        self.assertTrue(self.char1.move_to(self.room2, quiet=True))

    def test_guest_exits_are_available_without_other_local_object_commands(self):
        from evennia.commands.cmdhandler import get_and_merge_cmdsets

        class RestrictedCmdSet(CmdSet):
            priority = 100
            mergetype = "Replace"
            no_objs = True

            def at_cmdset_creation(self):
                self.add(Command(key="look"))

        class UnsafeCommand(Command):
            key = "unsafe"

        class UnsafeCmdSet(CmdSet):
            priority = 200

            def at_cmdset_creation(self):
                self.add(UnsafeCommand())

        self.room1.cmdset.add(UnsafeCmdSet, persistent=False)
        self.char1.cmdset.add(RestrictedCmdSet, persistent=False)
        self.char1.tags.add("character", category="guest")
        current, sets = self.char1.get_cmdsets(self.char1, self.char1.cmdset.current)
        self.assertTrue(current.no_objs)
        commands = [command for cmdset in sets for command in cmdset.commands]
        self.assertIn(self.exit.key.lower(), [command.key for command in commands])
        self.assertNotIn("unsafe", [command.key for command in commands])
        merged = get_and_merge_cmdsets(self.char1, [self.char1], "object", "out").result
        keys = {command.key for command in merged.commands}
        self.assertEqual(keys, {"look", "out"})

    def test_unrestricted_guest_discovery_lists_each_exit_once(self):
        from evennia.commands.cmdhandler import get_and_merge_cmdsets

        self.char1.tags.add("character", category="guest")
        merged = get_and_merge_cmdsets(self.char1, [self.char1], "object", "out").result
        self.assertEqual([command.key for command in merged.commands].count("out"), 1)
