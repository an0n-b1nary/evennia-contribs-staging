# evennia-posing

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

The pose pipeline for [Evennia](https://www.evennia.com/) games: pose, emit,
semipose, and say capture; a pose order tracker (`+pot`) and last-pose recall
(`+lastpose`); and two purely cosmetic player preferences — configurable pose
headers and per-reader name highlighting.

This is the **foundational** layer other RP systems build on. If you're
installing [evennia-rptracker](../evennia_rptracker) or
[evennia-scenes](../evennia_scenes), you almost certainly want this contrib
too — see "Recommended companion" below.

---

## What's included

| Name | Purpose |
|---|---|
| `PosingCharacterMixin` | Character mixin: `record_pose()`, pose state, pose-header/highlight `msg()` |
| `PosingRoomMixin` | Room mixin: pose-sorted character listing, name highlighting in room appearance |
| `pose_recorded` | Signal fired on every pose/emit/say/semipose |
| `commands.py` | `CmdPose`, `CmdEmit`, `CmdSemipose`, `CmdPot`, `CmdLastPose`, `CmdPoseHeader`, `CmdHighlight` |
| `highlighting.py` | `highlight_names()`, `format_pose_time()` — reusable utility functions |

**No Django models.** All state lives on Character/Room `AttributeProperty`
fields, so there is nothing to migrate.

---

## Installation

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_posing&egg=evennia_posing"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_posing"]
```

No migrations to run — this contrib has no models.

---

## Integration recipe

### 1. Mix the Character and Room typeclasses

```python
from evennia_posing import PosingCharacterMixin, PosingRoomMixin

class Character(PosingCharacterMixin, DefaultCharacter):
    ...

class Room(PosingRoomMixin, DefaultRoom):
    ...
```

`PosingCharacterMixin` must come **before** `DefaultCharacter` in the MRO —
it overrides `at_say`, `at_post_move`, `at_post_puppet`, `at_post_unpuppet`,
and `msg()`, each calling `super()` to chain into Evennia's defaults (and,
if present, any other mixins layered on top — see "Layering with
evennia-social" below).

### 2. Add the commands to your CharacterCmdSet

```python
from evennia_posing.commands import (
    CmdPose, CmdEmit, CmdSemipose, CmdPot, CmdLastPose,
    CmdPoseHeader, CmdHighlight,
)

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdPose)   # replaces Evennia's stock CmdPose
        self.add(CmdEmit)
        self.add(CmdSemipose)
        self.add(CmdPot)
        self.add(CmdLastPose)
        self.add(CmdPoseHeader)
        self.add(CmdHighlight)
```

### 3. Register the account options

Pose headers and name highlighting are player preferences stored via
Evennia's `OptionHandler`. Add these to `OPTIONS_ACCOUNT_DEFAULT` in
`server/conf/settings.py`:

```python
OPTIONS_ACCOUNT_DEFAULT["show_pose_headers"] = (
    "Show character name headers above poses.", "Boolean", True,
)
OPTIONS_ACCOUNT_DEFAULT["pose_header_format"] = (
    "Format string for pose headers ({name} placeholder required).",
    "Text", "--- {name} ---",
)
OPTIONS_ACCOUNT_DEFAULT["pose_separator"] = (
    "Visual separator between poses.", "Text", "",
)
OPTIONS_ACCOUNT_DEFAULT["highlight_enabled"] = (
    "Highlight character names in poses and room descriptions.",
    "Boolean", True,
)
OPTIONS_ACCOUNT_DEFAULT["highlight_self_color"] = (
    "Color for your own name in poses.", "Color", "w",
)
OPTIONS_ACCOUNT_DEFAULT["highlight_others_color"] = (
    "Color for other character names.", "Color", "c",
)
```

Without this step, `+poseheader`/`+highlight` will raise `ValueError: Option
not found!` the first time a player tries to change a setting (Evennia's
`OptionHandler.set()` requires the key to be pre-registered; `.get()` with a
default degrades gracefully, so *reading* current settings works even
unregistered, but *writing* does not).

### 4. Wire the `pose_recorded` signal (optional, but the point of this contrib)

`record_pose()` fires `pose_recorded` on every pose/emit/say. If you have
downstream consumers — an RP session tracker, a scene logger, an XP
collector — connect **one** listener and have it call them **in the order
you choose**. Django does not guarantee delivery order across multiple
independent receivers, so if ordering matters (it usually does — e.g. a
scene must be updated before session tracking reads room state), put all of
it in a single receiver:

```python
# your game's glue module, e.g. world/sandbox/glue.py
from django.dispatch import receiver
from evennia_posing.signals import pose_recorded

@receiver(pose_recorded)
def on_pose_recorded(sender, character, pose_text, pose_type, location, **kwargs):
    from evennia_scenes.capture import capture_to_scene
    from evennia_rptracker import record_rp_activity

    capture_to_scene(character, pose_text, log_type=pose_type)  # scene state first
    if location:
        record_rp_activity(character, location)                 # then rptracker
```

Connect the listener once, e.g. in your game's `AppConfig.ready()` or a
module imported at server start.

### 5. Character and room seams

Your character typeclass gets, from `PosingCharacterMixin`:

- `last_pose_time` — float unix timestamp, set on each pose/say and cleared
  on disconnect. This is the same seam `evennia-rptracker` documents as
  required — installing both contribs together means the seam is already
  satisfied.
- `last_pose_text`, `pose_status` (`"ic"` / `"observing"` / `"afk"`).

Your room typeclass gets, from `PosingRoomMixin`:

- `get_characters_by_pose_time()` — used by `+pot` and `+lastpose`.

---

## Layering with evennia-social

[evennia-social](../evennia_social) depends on this contrib and layers
ignore-filtering onto `msg()`. If you install both, put the social mixin
**before** the posing mixin so ignored content is filtered before header/
highlight processing runs:

```python
from evennia_posing import PosingCharacterMixin, PosingRoomMixin
from evennia_social import SocialCharacterMixin, SocialRoomMixin

class Character(SocialCharacterMixin, PosingCharacterMixin,
                 ObjectParent, DefaultCharacter):
    ...

class Room(SocialRoomMixin, PosingRoomMixin, ObjectParent, DefaultRoom):
    ...
```

---

## Recommended companion: evennia-rptracker / evennia-scenes

This contrib does **not** depend on `evennia-rptracker` or `evennia-scenes`
— it has no idea they exist, and they have no idea it exists. That's
deliberate: both of those contribs are designed to receive *fed* activity
and are agnostic about how poses happen, so a game could feed them from an
entirely different pose system if it wanted to.

If you *are* using the default pose system, though, `evennia-posing` is the
piece that satisfies the seam they document as "the game must provide" —
`last_pose_time` plus a call into `record_rp_activity()` /
`capture_to_scene()` on every pose. Wire it via the `pose_recorded` signal
(step 4 above) rather than overriding `record_pose()` yourself.

---

## Screen-reader support (optional)

Install the `[accessibility]` extra to get a plain-list rendering of `+pot`
for players with `screenreader_mode` enabled:

```
pip install -e "...&egg=evennia_posing[accessibility]"
```

Requires [evennia-accessibility](../../utils/evennia_accessibility). Falls
back to the standard fixed-width table when not installed — this is a soft
dependency, not a hard requirement.

---

## Settings reference

Account options (register in `OPTIONS_ACCOUNT_DEFAULT` — see step 3 above):

| Option | Default | Description |
|---|---|---|
| `show_pose_headers` | `True` | Show a header above each pose/say |
| `pose_header_format` | `"--- {name} ---"` | Header format string (`{name}` required) |
| `pose_separator` | `""` | Optional visual separator before the header |
| `highlight_enabled` | `True` | Highlight character names in poses/room descriptions |
| `highlight_self_color` | `"w"` | Color code for your own name |
| `highlight_others_color` | `"c"` | Color code for other characters' names |

No `settings.py` constants — this contrib has no configuration beyond the
account options above.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
