# evennia-lore

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Wiki-like lore compendium for [Evennia](https://www.evennia.com/) games. Players submit
and discover lore entries (`+lore`), investigate topics (`+investigate`), and passively
acquire entries as they RP. Storytellers share restricted content (`+share`). Staff
approve/reject submissions and manage the queue.

---

## What's included

| Component | Purpose |
|---|---|
| `LoreTag`, `LoreEntry`, `LoreVersion` | Core models |
| `LoreAcquisition`, `PlotLoreLink`, `LoreSceneLink`, `LoreRegionLink` | Bridge models (integer soft-refs) |
| `select_passive_lore()` | Weighted-random trickle acquisition engine |
| 5 commands | `+lore`, `+investigate`/`+inv`, `+share`, `+hint`, `+forget` |
| Website surface (`[web]`) | 11 views, accessible forms, Bootstrap 4 templates |
| DRF API (`[web]`) | `LoreEntryViewSet`, `LoreTagViewSet` |

---

## Installation

**Core** (models + commands + trickle engine, no web deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_lore&egg=evennia_lore"
```

**With web + API surface:**

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_lore&egg=evennia_lore[web]"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_lore"]
# For the [web] extra, also add:
INSTALLED_APPS += ["evennia_accessibility"]
```

**Run migrations:**

```
evennia migrate evennia_lore
```

---

## Add commands to your CharacterCmdSet

```python
from evennia_lore.commands import CmdLore, CmdInvestigate, CmdShare, CmdHint, CmdForget

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdLore)
        self.add(CmdInvestigate)
        self.add(CmdShare)
        self.add(CmdHint)
        self.add(CmdForget)
```

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `LORE_STAFF_LOCK` | `"cmd:perm(Builder)"` | Staff lock for approve/reject/unflag/share operations; also used by web views and API |
| `LORE_REQUIRE_APPROVAL` | `False` | When True, submissions start as SUBMITTED (awaiting staff review) instead of PUBLISHED |
| `LORE_PASSIVE_WEEKLY_CEILING` | `5` | Max passive acquisitions per character per week |
| `LORE_PASSIVE_LEAN_MULTIPLIER` | `Decimal("2.0")` | Weight multiplier for lean-matching entries |
| `LORE_SESSION_CONTEXT_PROVIDER` | `None` | Dotted path to your session context provider (see below) |
| `LORE_RPTRACKER_APP_LABEL` | `"evennia_rptracker"` | App label for the rptracker contrib |
| `LORE_SCENES_APP_LABEL` | `"scenes"` | App label for scenes (used for scene links + hint regions) |
| `LORE_PLOTS_APP_LABEL` | `"plots"` | App label for plots (used for plot-lore links and lean) |
| `LORE_REGIONS_APP_LABEL` | `"regions"` | App label for regions (used for region weighting and hint) |

---

## Passive lore trickle

The `select_passive_lore(character, session)` function is called at RPSession end (when
rptracker is installed). It builds a weighted pool of eligible entries and picks one
proportionally:

| Signal | Weight |
|---|---|
| Linked to an active plot thread (via PlotLoreLink) | 8 |
| Room directly tagged on entry | 5 |
| Region linked (via LoreRegionLink) | 3 |
| Major tag match | 2 |
| Any tag match | 1 |

An entry with weight 0 is excluded. The lean multiplier doubles the weight for entries
matching the character's `+investigate` lean.

### Session context provider

Cross-domain context (room_id / region_id / thread_ids for a session) is supplied by a
callable you register at `LORE_SESSION_CONTEXT_PROVIDER`. Without a provider the engine
still works, degrading to tag-only weighting.

**Provider contract:**

```python
def get_session_context(session) -> dict:
    """
    Returns:
        {
            "room_id": int | None,   # ObjectDB pk of the session's room
            "region_id": int | None, # Region pk containing the room
            "thread_ids": set[int],  # PlotThread pks active during the session
        }
    """
```

**Worked example using the rptracker + scenes + plots contribs:**

```python
# my_game/lore_provider.py
def get_session_context(session):
    room_id = session.room.pk if session.room else None
    region_id = None
    thread_ids = set()

    if room_id:
        from evennia_lore.models import LoreRegionLink
        # Resolve region via your region membership bridge
        from my_game.regions import RegionMembership
        membership = RegionMembership.objects.filter(room_id=room_id).first()
        if membership:
            region_id = membership.region_id

    # Resolve active plot threads via scene links
    from evennia_rptracker.models import RPSessionSceneLink
    from evennia_scenes.models import ScenePlotLink  # if you have this
    scene_ids = set(
        RPSessionSceneLink.objects.filter(session=session).values_list("scene_id", flat=True)
    )
    if scene_ids:
        thread_ids = set(
            ScenePlotLink.objects.filter(scene_id__in=scene_ids).values_list("thread_id", flat=True)
        )

    return {"room_id": room_id, "region_id": region_id, "thread_ids": thread_ids}

# settings.py
LORE_SESSION_CONTEXT_PROVIDER = "my_game.lore_provider.get_session_context"
```

---

## Soft-partner matrix

The trickle and bridge cleanup register only when the partner app is present:

| Partner app | When present | Effect when absent |
|---|---|---|
| `LORE_RPTRACKER_APP_LABEL` | Register `rp_session_ended` listener (trickle fires) | Trickle dormant; model/API still ship |
| `LORE_SCENES_APP_LABEL` | Register `connect_soft_ref_cleanup` for Scene→LoreSceneLink | LoreSceneLink rows orphaned on hard-delete (rare; harmless) |
| `LORE_PLOTS_APP_LABEL` | Register cleanup for PlotThread→PlotLoreLink | Same |
| `LORE_REGIONS_APP_LABEL` | Register cleanup for Region→LoreRegionLink | Same |

---

## Web surface (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("lore/", include("evennia_lore.urls"))]
```

URL names: `lore-list`, `lore-create`, `lore-compendium`, `lore-queue`, `lore-lean`,
`lore-detail`, `lore-edit`, `lore-history`, `lore-diff`, `lore-approve`, `lore-reject`.

---

## REST API (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("api/v1/", include("evennia_lore.api.urls"))]
```

Generates `/api/v1/lore/`, `/api/v1/lore/<id>/`, `/api/v1/lore-tags/`, `/api/v1/lore-tags/<id>/`.

Privacy rules:
- Staff (LORE_STAFF_LOCK) see all non-archived entries.
- Non-staff see only PUBLISHED entries.
- RESTRICTED `body` is `null` unless the caller has a `LoreAcquisition` row.

---

## Programmatic API

```python
from evennia_lore.models import LoreEntry, LoreAcquisition, LoreSceneLink

# Submit a new entry programmatically (author=None for system-generated):
entry = LoreEntry.create_entry(
    title="The Founding",
    author=character,
    body="In the beginning...",
    privacy="public",
)

# Record an acquisition (storyteller share):
LoreAcquisition.objects.get_or_create(
    entry=entry,
    character=target_char,
    defaults={
        "character_name": target_char.key,
        "source": LoreAcquisition.Source.STORYTELLER,
    },
)

# Link to a scene (scene_id is an integer soft-reference):
LoreSceneLink.objects.get_or_create(entry=entry, scene_id=scene.pk)
```

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
