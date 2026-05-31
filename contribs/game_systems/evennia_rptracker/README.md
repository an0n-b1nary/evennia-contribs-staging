# evennia-rptracker

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

Passive RP session detection and tracking for [Evennia](https://www.evennia.com/) games.
Detects when characters are engaged in RP (posing in the same IC room) without
requiring players to start or stop anything manually. Sessions accumulate and are
available for downstream reward systems (XP, lore, etc.).

---

## What's included

| Name | Purpose |
|---|---|
| `RPSession` | A detected stretch of RP activity (status: pending/active/completed/flagged) |
| `RPSessionPartner` | Through-model recording active partners per session |
| `RPSessionSceneLink` | Integer soft-ref bridge: session ↔ scene (no FK to scenes app) |
| `tracker.py` | In-memory state machine, lifecycle hooks, idle-check Script |
| `antigaming.py` | `sweep_rp_sessions()` — pose-spam + manual-end-abuse detection |
| `commands.py` | `CmdActivity` (+activity) + `CmdRPTrackerStaff` (+rptracker) |
| `bridges_scenes.py` | Soft-dep listener: creates `RPSessionSceneLink` rows when scenes are active |

---

## Installation

This contrib depends on [evennia-links](../../base_systems/evennia_links) `>= 0.2`
(it provides `AbstractLink`, the base of `RPSessionSceneLink`, plus the
soft-reference cleanup helper). Install both:

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/base_systems/evennia_links&egg=evennia_links"
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_rptracker&egg=evennia_rptracker"
```

Add both to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_rptracker"]
```

**Run migrations:**

```
evennia migrate
```

---

## Integration recipe

### 1. Feed activity from your pose hook

In your `Character` typeclass, call `record_rp_activity` whenever the
character poses, says, or emits something in-game:

```python
from evennia_rptracker import record_rp_activity

class Character(DefaultCharacter):
    def record_pose(self, pose_text, pose_type="pose"):
        self.last_pose_time = time.time()  # required — see Character seams below
        # ... your existing pose logic ...
        record_rp_activity(self, self.location)
```

### 2. Wire server lifecycle hooks

In `server/conf/at_server_startstop.py`:

```python
def at_server_start():
    from evennia_rptracker import recover_orphaned_sessions, ensure_idle_check_running
    recover_orphaned_sessions()
    ensure_idle_check_running()

def at_server_stop():
    from evennia_rptracker import flush_all_sessions
    flush_all_sessions()
```

### 3. Wire the disconnect hook

In your `Character` typeclass:

```python
def at_post_unpuppet(self, account, session=None, **kwargs):
    from evennia_rptracker import end_session
    end_session(self.id, manual=False)
    super().at_post_unpuppet(account, session=session, **kwargs)
```

### 4. Add commands to your CharacterCmdSet

```python
from evennia_rptracker.commands import CmdActivity, CmdRPTrackerStaff

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdActivity)
        self.add(CmdRPTrackerStaff)
```

### 5. Character and room seams

Your character typeclass must expose:

- `character.last_pose_time` — float unix timestamp, set on each pose and
  cleared on disconnect. Used to determine which characters are "actively
  posing" (within `RPTRACKER_PARTNER_ACTIVE_WINDOW` seconds).

Your room typeclass may expose:

- `room.room_type` — string. Only rooms with `room_type == "ic"` are tracked.
  Rooms without this attribute are treated as `"ic"`. Set `room_type = "ooc"`
  on OOC or staff rooms to exclude them.
- `room.active_scene_id` — int or None. Used by the optional scene bridge
  (see Scene bridge below). Not needed if scenes are not installed.

NPC exclusion: characters tagged `"npc"` in category `"npc_system"` are
automatically excluded from tracking and partner detection.

---

## Settings reference

Add any of these to `server/conf/settings.py`. All have sensible defaults.

| Setting | Default | Description |
|---|---|---|
| `RPTRACKER_SESSION_IDLE_TIMEOUT` | `3600` | Seconds of inactivity before a session closes |
| `RPTRACKER_PARTNER_ACTIVE_WINDOW` | `3600` | Seconds a partner's last pose counts as "active" |
| `RPTRACKER_SESSION_ACTIVATION_POSES` | `2` | Poses needed to activate a pending session |
| `RPTRACKER_POSE_FLUSH_THRESHOLD` | `5` | Flush pose_count to DB every N poses |
| `RPTRACKER_IDLE_CHECK_INTERVAL` | `300` | Seconds between idle-check Script runs |
| `RPTRACKER_MANUAL_END_ABUSE_COUNT` | `3` | Manual ends per day before auto-flag |
| `RPTRACKER_POSE_SPAM_MIN_COUNT` | `20` | Pose count threshold for spam detection |
| `RPTRACKER_POSE_SPAM_MAX_SECONDS` | `600` | Total duration threshold (10 min) |
| `RPTRACKER_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock string for `CmdRPTrackerStaff` |
| `RPTRACKER_XP_PROJECTION` | `None` | Dotted path: `(char_pk, window_end) → list[str] \| None` |
| `RPTRACKER_SCENE_DISPLAY` | `None` | Dotted path: `(scene_id) → str` |
| `RPTRACKER_FLAG_REVIEW_HOOK` | `None` | Dotted path: `(title, description) → None` |
| `RPTRACKER_SCENES_APP_LABEL` | `"scenes"` | App label for the optional scenes partner |

---

## XP integration

XP is entirely the consuming game's responsibility. `is_xp_eligible()` on
`RPSession` provides a sensible default (COMPLETED + ≥30 min + ≥1 partner +
not yet awarded), but your XP collector queries and award logic live in your
game code.

Call `sweep_rp_sessions(window_end)` **before** your XP collectors so flagged
sessions are excluded:

```python
from evennia_rptracker import sweep_rp_sessions
from myapp.collectors import collect_rp_xp

def run_weekly_batch(window_end):
    sweep_rp_sessions(window_end)  # flag suspicious sessions first
    for award in collect_rp_xp(window_end):
        ...
```

Wire `RPTRACKER_FLAG_REVIEW_HOOK` to route auto-flag notifications to your
staff queue (e.g. a ticket system):

```python
RPTRACKER_FLAG_REVIEW_HOOK = "myapp.jobs.create_review_ticket"
```

---

## Scene bridge (optional)

When a scenes contrib is installed, `RPSessionSceneLink` rows are created
automatically for each session↔scene overlap. This requires:

1. A scenes app installed under the label set by `RPTRACKER_SCENES_APP_LABEL`
   (default `"scenes"`). The app must have a `Scene` model.
2. Your room typeclass setting `room.active_scene_id` when a scene is active.

(`evennia-links`, already a required dependency, provides the
`connect_soft_ref_cleanup` hook that removes orphaned links on scene deletion.)

`RPSessionSceneLink.scene_id` is a plain integer (no FK), so the bridge table
has no DB dependency on the scenes app — install order doesn't matter.
When a Scene is hard-deleted, orphaned links are cleaned by the
`connect_soft_ref_cleanup` hook (registered in `ready()`).

> **Note:** The `RPTRACKER_SCENES_APP_LABEL` setting gates which app is treated
> as the scenes partner. The bridge's FK string is hardcoded to `"scenes.Scene"`,
> so the partner app must be installed under the label `"scenes"` for the
> bridge to resolve correctly. This is a v0.1 limitation.

Wire `RPTRACKER_SCENE_DISPLAY` to resolve scene IDs to human-readable strings
in `+activity/detail`:

```python
RPTRACKER_SCENE_DISPLAY = "myscenes.display.render_scene_ref"
# callable: (scene_id: int) -> str
```

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
