"""
Room

Rooms are simple containers that has no location of their own.

Contrib sandbox extensions (mixin-based, no hand-rolled hooks):
- `SocialRoomMixin` (evennia_social) — hangout-directory designation
  (`hangout_type`) and per-room teleport access control (`allow_teleport`),
  read by `+hangouts`/`+where`/`@tel`.
- `PosingRoomMixin` (evennia_posing) — pose-sorted character listing (used
  by `+pot`/`+lastpose`) and name highlighting in room appearance.

Game-owned attributes kept on this class directly (not provided by either
mixin):
- `room_type` — a shared game-level attribute read by evennia_rptracker
  (only "ic" rooms are tracked), evennia_scenes, and evennia_social's
  `+where`. Owned by no single contrib, per evennia_social's README
  attribute table — rooms without it default to "ic" on the rptracker
  side, but we set it explicitly here so seed content can flip specific
  rooms to "ooc".
- `active_scene_id` — evennia_scenes' integration contract: the room stores
  the active scene's pk here, an Evennia Attribute (not a Django FK), so
  cross-domain consumers (rptracker's scene bridge) can read it without a
  hard dependency on evennia_scenes.
- `at_object_receive` override — registers arriving player characters as
  scene participants, per evennia_scenes' "Wire capture hooks" recipe.
  Evennia ships no room-receive signal, so this stays hand-wired.
"""

from evennia.objects.objects import DefaultRoom
from evennia.typeclasses.attributes import AttributeProperty

from evennia_posing import PosingRoomMixin
from evennia_social import SocialRoomMixin

from .objects import ObjectParent


class Room(SocialRoomMixin, PosingRoomMixin, ObjectParent, DefaultRoom):
    """
    Rooms are like any Object, except their location is None
    (which is default). They also use basetype_setup() to
    add locks so they cannot be puppeted or picked up.
    (to change that, use at_object_creation instead)

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects.
    """

    # "ic" (tracked by evennia_rptracker) or "ooc" (excluded). Rooms without
    # this attribute default to "ic" on the rptracker side; set explicitly
    # here so seed content can mark OOC rooms.
    room_type = AttributeProperty(default="ic")

    # Integer pk of the active evennia_scenes Scene, or None. See module
    # docstring — this is the contrib's documented integration contract.
    active_scene_id = AttributeProperty(default=None, autocreate=False)

    def at_object_receive(self, moved_obj, source_location, move_type="move", **kwargs):
        """Auto-register arriving player characters as scene participants.

        evennia_scenes ships no room-receive signal, so this must be wired
        manually (see its README §"Capture hooks").
        """
        super().at_object_receive(moved_obj, source_location, move_type=move_type, **kwargs)
        if moved_obj.has_account:
            from evennia_scenes.capture import register_room_entry

            register_room_entry(self, moved_obj)
