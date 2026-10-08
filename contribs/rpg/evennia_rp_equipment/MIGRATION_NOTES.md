# Migration notes — evennia-rp-equipment

This preview package is contrib-native: it was written here, not extracted
from a running game. It ships no game-specific slots, stat names or items.

## First adoption

Install pinned `evennia-links`, `evennia-rp-rules` and `evennia-rp-chargen`
(0.3 or later), then this package, and add `evennia_rp_equipment` to
`INSTALLED_APPS` after `evennia_rp_chargen`. There are no models, so there's
nothing to migrate. Items are ordinary Evennia objects; their state lives in
Attributes and Tags.

Wire the character display (the mixin, or the `display` helpers from your own
overrides), add `EquipmentCmdSet`, and optionally call
`audit.log_problems()` from `at_server_start()`.

Existing objects in a game don't become equipment. Equipment is anything whose
typeclass includes `EquipmentMixin`. To convert existing items, swap their
typeclass and set `worn_line` and `slot`. Converted items have no maker, so
nobody can edit them; set `maker_id` if a player should.

## 0.1.0

The first release.
