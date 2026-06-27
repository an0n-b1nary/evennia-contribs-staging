# evennia-plots

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Narrative plot management for [Evennia](https://www.evennia.com/) games. Players
open and conclude storyline threads (`+plot`), linking them to scenes, calendar
events, and board posts. Concluded threads award a 0–5 XP bonus based on
engagement. Staff curate story arcs (`+arc`) with per-source XP multipliers, log
hook decisions (`+hook`), and control a single globally-current arc that gates
XP rates across the game.

---

## What's included

| Component | Purpose |
|---|---|
| `PlotThread`, `PlotArc`, `PlotTag` | Core domain models |
| `PlotParticipant`, `PlotUpdate`, `PlotUpdateVersion` | Journaling + version history |
| `ThreadLink` | Sequel/related links between threads |
| `ScenePlotLink`, `PlotCalendarLink`, `PlotBoardLink` | Bridge models (integer soft-refs) |
| `PlotBonusCredit` | Idempotent XP-award eligibility rows |
| `+plot` | Thread lifecycle, linking, journaling |
| `+arc` (staff) | Arc management + per-source XP multiplier overrides |
| `+hook` (staff) | Anti-favoritism audit log |
| `gating.py` | `resolve_xp_multiplier()` — arc-aware XP rate resolver |
| `collectors.py` (`[xp]`) | Thread-bonus + arc-bonus XP collectors |
| `antigaming.py` (`[xp]`) | Flag <24h-old thread conclusions before XP award |
| Website surface (`[web]`) | ~18 views, accessible forms, 14 templates |
| DRF API (`[web]`) | `PlotThreadViewSet` with privacy gating |

---

## Dependencies

| Dep | Kind | Reason |
|---|---|---|
| `evennia>=6.0` | required | framework |
| `evennia-links>=0.2` | required | `AbstractVersion`, `AbstractAuthoredLink`, `connect_soft_ref_cleanup`, `connect_on_ready` |
| `evennia-accessibility>=0.1` | `[web]` | accessible forms/templates |
| `djangorestframework>=3.14` | `[web]` | REST API |
| `django-filter>=23` | `[web]` | `PlotThreadFilter` |
| `evennia-xp>=0.1` | `[xp]` | XP batch collectors + anti-gaming sweep |

---

## Installation

**Core** (models + commands + XP gating, no web or XP batch deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_plots&egg=evennia_plots"
```

**With web + API surface:**

```
pip install -e "...evennia_plots[web]"
```

**With XP batch integration:**

```
pip install -e "...evennia_plots[xp]"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_plots"]
# For the [web] extra, also add:
INSTALLED_APPS += ["evennia_accessibility"]
```

**Run migrations:**

```
evennia migrate evennia_plots
```

---

## Add commands to your CharacterCmdSet

```python
from evennia_plots.commands import CmdPlot, CmdArc, CmdHook

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdPlot)

class StaffCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdArc)
        self.add(CmdHook)
```

---

## XP integration

Register the seams in your settings when `evennia-xp` (`[xp]`) is installed:

```python
# Multiplier: arc-aware — called for every XP award in the batch.
XP_MULTIPLIER_RESOLVER = "evennia_plots.gating.resolve_xp_multiplier"

# Collectors: called each week to emit thread-bonus and arc-bonus awards.
XP_COLLECTORS = [
    ("thread_bonus", "evennia_plots.collectors.collect_thread_bonuses"),
    ("arc_bonus",    "evennia_plots.collectors.collect_arc_bonuses"),
]

# Anti-gaming: called before the batch to zero out suspicious threads.
XP_ANTIGAMING_SWEEPS = [
    "evennia_plots.antigaming.sweep",
]
```

These settings are no-ops unless `evennia-xp` is installed.

---

## Settings reference

| Setting | Default | Purpose |
|---|---|---|
| `PLOTS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock expression that grants staff access to `+arc`, `+hook`, and staff-only `+plot` switches. The `cmd:` prefix is stripped before evaluation. |
| `PLOTS_SCENES_APP_LABEL` | `"scenes"` | Django app label for the scenes app; used by `apps.py` to register soft-ref cleanup for `ScenePlotLink.scene_id`. |
| `PLOTS_CALENDAR_APP_LABEL` | `"calendar"` | Same, for `PlotCalendarLink.event_id`. |
| `PLOTS_BOARDS_APP_LABEL` | `"boards"` | Same, for `PlotBoardLink.post_id`. |
| `SITE_URL` | `""` | When set, `+plot` output includes a clickable web URL link to the thread's detail page. |

---

## Privacy model

`PlotThread.privacy` controls who can view and link:

| Privacy | Viewable by | Linkable by |
|---|---|---|
| `PUBLIC` | Anyone | Anyone (thread must be ACTIVE) |
| `INVITE_ONLY` | Anyone | Invited characters or staff only |
| `PRIVATE` | Creator + staff | Creator + staff |

The web `PlotDetailView` excludes PRIVATE threads from its queryset entirely
(404 for unauthenticated or non-staff visitors). The API `PlotThreadViewSet`
hides PRIVATE threads and non-ACTIVE threads from non-staff users.

---

## Thread bonus XP (0–5 points)

When a thread is concluded, `_compute_bonus_xp()` tallies three checklist rules:

| Rule | Points | Condition |
|---|---|---|
| Advance notice | +3 | A `PlotCalendarLink` with `advance_notice_met=True` (event was scheduled ≥7 days ahead) |
| Multi-scene | +1 | At least 2 `ScenePlotLink` entries |
| IC post | +1 | At least one `PlotBoardLink` with `is_ic_post=True` |

The result is stored in `bonus_xp_computed`. The anti-gaming sweep zeroes it for
threads concluded within 24 h of creation. The collector applies the active arc's
multiplier before emitting the award.

---

## Arc XP multipliers

`PlotArc` stores a per-source multiplier for each of the five XP sources:

| Source key | Default (STORY) | Default (DOWNTIME) |
|---|---|---|
| `rp_session` | 1.0× | 0.0× |
| `cutscene` | 1.0× | 0.0× |
| `lore` | 1.0× | 0.0× |
| `thread_bonus` | 1.0× | 0.0× |
| `rp_channel_session` | 1.0× | 0.0× |

Staff can override any source via `+arc/xp-set #N rp_session=2.5`. A DOWNTIME
arc with all multipliers at 0× effectively pauses XP for the game while allowing
players to continue playing. At most one arc can be `is_current=True` at a time
(enforced by a partial unique constraint).

---

## Signals

All 12 signals are exported directly from `evennia_plots`:

```python
from evennia_plots import (
    plot_thread_created, plot_thread_activated, plot_thread_concluded,
    plot_thread_archived, scene_linked_to_thread, post_linked_to_thread,
    event_linked_to_thread, thread_link_accepted, plot_update_created,
    plot_thread_edited, arc_type_changed, arc_currency_changed,
)
```

---

## Programmatic API

```python
from evennia_plots.models import PlotThread, PlotArc, ScenePlotLink
from evennia_plots.gating import resolve_xp_multiplier

# Create a thread
thread = PlotThread.create_thread(name="The Dragon Crisis", creator=character)

# Activate and conclude
thread.activate()
bonus = thread.conclude()  # returns int 0–5

# Link a scene (accepts any object with .pk)
ScenePlotLink.create_link(scene=scene_obj, thread=thread, linked_by=character)

# Look up the arc-adjusted multiplier for any XP source
mult = resolve_xp_multiplier("rp_session", thread=thread)
```
