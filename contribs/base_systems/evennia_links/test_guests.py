"""Guest identity and movement policy without a host's command composition."""

from unittest.mock import MagicMock

from evennia.accounts.accounts import DefaultGuest
from evennia.objects.objects import DefaultCharacter
from evennia.utils.create import create_account
from evennia.utils.test_resources import EvenniaTest

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

    def test_tagged_guest_boundary_cannot_be_disabled_with_move_hooks(self):
        self.char1.tags.add("character", category="guest")
        self.assertFalse(self.char1.move_to(self.room2, move_hooks=False))
        self.room2.tags.add("wing", category="guest")
        self.assertTrue(self.char1.move_to(self.room2, quiet=True))
