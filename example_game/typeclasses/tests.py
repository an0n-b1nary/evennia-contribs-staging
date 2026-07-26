"""Sandbox integration tests for the game's typeclass composition.

Verifies the game-side contract between example_game's typeclasses and the
evennia_posing / evennia_social mixins: MRO order (social before posing, per
both contribs' README integration recipes) and that the game-owned attribute
seams resolve with their documented defaults. Contrib internals are covered
by the contribs' own suites - this only checks the composition in
typeclasses/characters.py and typeclasses/rooms.py.
"""

from evennia.utils.test_resources import EvenniaTest

from evennia_posing import PosingCharacterMixin, PosingRoomMixin
from evennia_social import SocialCharacterMixin, SocialRoomMixin
from typeclasses.characters import Character
from typeclasses.rooms import Room


class TestTypeclassComposition(EvenniaTest):
    """Contract (a): mixin MRO order + game-owned attribute seams."""

    character_typeclass = Character
    room_typeclass = Room

    def test_character_mro_social_before_posing(self):
        """SocialCharacterMixin precedes PosingCharacterMixin in the MRO -
        required msg() cooperative order (ignore-filter before headers)."""
        self.assertTrue(issubclass(Character, SocialCharacterMixin))
        self.assertTrue(issubclass(Character, PosingCharacterMixin))
        mro = Character.__mro__
        self.assertLess(mro.index(SocialCharacterMixin), mro.index(PosingCharacterMixin))

    def test_room_mro_has_both_mixins(self):
        self.assertTrue(issubclass(Room, SocialRoomMixin))
        self.assertTrue(issubclass(Room, PosingRoomMixin))

    def test_room_seams_resolve(self):
        """room_type defaults to "ic"; active_scene_id resolves to None."""
        self.assertEqual(self.room1.room_type, "ic")
        self.assertIsNone(self.room1.active_scene_id)

    def test_character_posing_state_resolves(self):
        """Mixin-provided pose state resolves on the Character. char2 is
        never puppeted in EvenniaTest setUp, but creating it with a
        location still runs DefaultObject.at_first_save()'s at_post_move(),
        which PosingCharacterMixin overrides to stamp last_pose_time and
        reset last_pose_text - so the seam resolves to a real timestamp
        here, not the class-level AttributeProperty default of None."""
        self.assertIsInstance(self.char2.last_pose_time, float)
        self.assertEqual(self.char2.pose_status, "ic")
        self.assertEqual(self.char2.last_pose_text, "")
