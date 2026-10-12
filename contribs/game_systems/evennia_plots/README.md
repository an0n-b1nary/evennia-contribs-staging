# evennia-plots

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Narrative plot management for [Evennia](https://www.evennia.com/) games. Players
open and conclude plots (`+plot`), linking them to scenes, calendar events, and
board posts, and run them together through **threads**: the open questions,
problems and leads inside a plot. Owners can mark threads whose answer they
already hold, and seal that answer until it is revealed. Concluded plots award a
0–5 XP bonus based on engagement; threads never affect XP. Staff curate story
arcs (`+arc`) with per-source XP multipliers, log hook decisions (`+hook`), and
control a single globally-current arc that gates XP rates across the game.

> **Names.** Players say *plot* and *thread*. In code a plot is still
> `PlotThread` and a thread is `StoryThread`; the code names are planned to
> change in a declared breaking 1.0.

---

## What's included

| Component | Purpose |
|---|---|
| `PlotThread` (a plot), `PlotArc`, `PlotTag` | Core domain models |
| `PlotOwner` | Who runs a plot (never affects XP) |
| `StoryThread`, `StoryThreadInterest`, `StoryThreadAnswerVersion` | Threads, leads and interest, sealed-answer history |
| `threads.py` | Every thread and owner rule, shared by `+plot` and the web |
| `PlotParticipant`, `PlotUpdate`, `PlotUpdateVersion` | Journaling + version history |
| `ThreadLink` | Sequel/related links between plots |
| `ScenePlotLink`, `PlotCalendarLink`, `PlotBoardLink` | Bridge models (integer soft-refs) |
| `PlotBonusCredit` | Idempotent XP-award eligibility rows |
| `+plot` | Plot lifecycle, owners, threads, linking, journaling |
| `+arc` (staff) | Arc management + per-source XP multiplier overrides |
| `+hook` (staff) | Anti-favoritism audit log |
| `gating.py` | `resolve_xp_multiplier()` — arc-aware XP rate resolver |
| `collectors.py` (`[xp]`) | Plot-bonus + arc-bonus XP collectors |
| `antigaming.py` (`[xp]`) | Flag <24h-old plot conclusions before XP award |
| Website surface (`[web]`) | ~24 views, accessible forms, 20 templates |
| DRF API (`[web]`) | `PlotThreadViewSet` with privacy gating, owners and threads |

---

## Dependencies

| Dep | Kind | Reason |
|---|---|---|
| `evennia>=6.0` | required | framework |
| `evennia-links>=0.5` | required | `AbstractVersion`, `AbstractAuthoredLink`, `connect_soft_ref_cleanup`, `connect_on_ready`, shared web staff policy |
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
XP_MULTIPLIER_RESOLVER = "evennia_plots.integrations.gating.resolve_xp_multiplier"

# Collectors: called each week to emit plot-bonus and arc-bonus awards.
XP_COLLECTORS = [
    ("thread_bonus", "evennia_plots.integrations.xp.collect_thread_bonuses"),
    ("arc_bonus",    "evennia_plots.integrations.xp.collect_arc_bonuses"),
]

# Anti-gaming: called before the batch to zero out suspicious plots.
XP_ANTIGAMING_SWEEPS = [
    "evennia_plots.integrations.antigaming.sweep",
]
```

These settings are no-ops unless `evennia-xp` is installed.

---

## Settings reference

| Setting | Default | Purpose |
|---|---|---|
| `PLOTS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock expression that grants staff access to `+arc`, `+hook`, and staff-only `+plot` switches. The `cmd:` prefix is stripped before evaluation. |
| `PLOTS_SCENES_APP_LABEL` | `"evennia_scenes"` | Django app label for the scenes app; used by `apps.py` to register soft-ref cleanup for `ScenePlotLink.scene_id`. |
| `PLOTS_CALENDAR_APP_LABEL` | `"evennia_calendar"` | Same, for `PlotCalendarLink.event_id`. |
| `PLOTS_BOARDS_APP_LABEL` | `"evennia_boards"` | Same, for `PlotBoardLink.post_id`. |
| `PLOTS_MAPS_APP_LABEL` | `"evennia_maps"` | When that app is installed (evennia-maps 0.9+), adds a "Plots here" section to the live map's room panel. See below. |
| `SITE_URL` | `""` | When set, `+plot` output includes a clickable web URL link to the plot's detail page. |

---

## Privacy model

`PlotThread.privacy` controls who can view and link:

| Privacy | Viewable by | Linkable by |
|---|---|---|
| `PUBLIC` | Anyone | Anyone (plot must be ACTIVE) |
| `INVITE_ONLY` | Anyone | Owners, invited characters or staff |
| `PRIVATE` | Owners + staff | Owners + staff |

The web `PlotDetailView` excludes PRIVATE plots from its queryset entirely
(404 for unauthenticated or non-staff visitors), and so do the owner and thread
pages. The API `PlotThreadViewSet` hides PRIVATE plots and non-ACTIVE plots
from non-staff users.

---

## Owners

`PlotOwner` rows say who runs a plot. The creator is the first owner, and
`+plot/owner <#N>=<character>` (or the web's *Manage Owners* page) adds more.
Owners edit the plot, manage invitations, conclude it, and manage its threads.
A plot keeps at least one owner unless staff remove the last. Ownership is
separate from `PlotParticipant`, which decides who receives the conclusion
bonus, so adding an owner never hands out XP. `plot.is_owner(character)` and
`plot.can_manage(character)` (owner or staff) are the checks partner contribs
should use; `creator` remains as history.

When staff take an owner's action on a plot they don't own (adding or removing
owners, resolving a held thread, revealing an answer, and so on) it is recorded
in the plot's `staff_log`, which owners and staff can read and which is never
trimmed.

---

## Threads

A `StoryThread` is an open question, problem or lead inside one plot,
referenced as `#<plot>.<thread>` (`#12.3`). All the rules live in
`evennia_plots.threads`, which both `+plot` and the web views call.

**Who may add threads** is the plot's `thread_policy`:

| Policy | Adds directly | May request |
|---|---|---|
| `open` (default) | Owners, staff, anyone passing `can_link` | — |
| `request` | Owners and staff | Anyone passing `can_link`; owners accept or decline |
| `owners` | Owners and staff | — |

Owners can seed threads while a plot is still proposed. Every thread title is
visible to anyone who can see the plot; pending and declined requests are shown
only to owners, staff and the requester.

**Lifecycle:** `requested → open | declined` (a requester may withdraw, which
deletes the request); `open → resolved | dropped`, and back with reopen;
concluding or archiving the plot turns open threads into `loose_end` and
declines pending requests, without blocking. A loose end can be **carried**
into a declared sequel (`+plot/sequel`) by someone who manages both plots,
becoming a new open thread there.

**Leads and interest** are social signals. Any number of characters may lead.
A lead, or the thread's creator, may resolve a thread that isn't held.

### Held threads and sealed answers

Owners mark a thread **held** when they already know its answer. A plot with an
open held thread is *Owner-led* (computed, never stored). Owners may write the
answer down as a **sealed answer**: readable only by owners and staff, with
every earlier wording kept in `StoryThreadAnswerVersion`. Sealing marks the
thread held, and a held thread with an answer can't be released until the
answer is cleared (a database constraint backs this).

The answer is revealed only by choice: when resolving or dropping the thread,
or later with `+plot/thread/reveal`. Once revealed, anyone who can see the plot
can read it and its history. A sealed answer is never shown in `+plot <#N>`,
on the plot page, in the API (revealed or not), on the map, or to a carried
thread's new owners: carrying copies it only when every owner of the sequel
also owns the source plot.

Threads have no effect on XP, in either direction.

---

## On the map

With evennia-maps 0.9+ and evennia-scenes installed, clicking a room on the live map
lists the plots that have had a scene there, in a "Plots here" section of its
room panel. Plots record no places of their own, so a plot reaches a room only
through a `ScenePlotLink` to a scene held there. Both privacy rules apply:

- **Scenes:** players count only scenes the web may show, so a view-private scene
  never reveals that a plot passed through a room.
- **Plots:** private plots are left out for players, as on the plot pages. Staff
  see them, noted "private" and unlinked, because the plot page doesn't serve them.

Active and concluded plots are listed, newest first, up to ten; proposed and archived
ones are not. Each notes its arc when it has one.

---

## Plot conclusion bonus XP (0–5 points)

When a plot is concluded, `_compute_bonus_xp()` tallies three checklist rules:

| Rule | Points | Condition |
|---|---|---|
| Advance notice | +3 | A `PlotCalendarLink` with `advance_notice_met=True` (event was scheduled ≥7 days ahead) |
| Multi-scene | +1 | At least 2 `ScenePlotLink` entries |
| IC post | +1 | At least one `PlotBoardLink` with `is_ic_post=True` |

The result is stored in `bonus_xp_computed`. The anti-gaming sweep zeroes it for
plots concluded within 24 h of creation. The collector applies the active arc's
multiplier before emitting the award. Threads and owners play no part. The XP
source key stays `thread_bonus` (it is stored in XP logs); its label is "Plot
Bonus".

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
from evennia_plots.integrations.gating import resolve_xp_multiplier

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

## Upgrading to 0.7.0

- **Migrations.** `0002` adds owners, threads and the thread policy; `0003`
  makes every existing plot's creator its first owner. Run `evennia migrate`.
  Nothing existing is renamed, and plot numbers and primary keys are unchanged,
  so partner soft-references stay valid.
- **The `+thread` alias is gone.** `+thread` used to mean `+plot`; threads are
  now part of a plot (`+plot/thread`), so the alias would mislead.
- **Owners replace the creator in permission checks.** Anything that checked
  `creator_id` to decide who manages a plot should call `plot.is_owner()` or
  `plot.can_manage()`.
- **Player-facing wording** says "plot" where it said "plot thread", in
  commands, pages and guides. Code names are unchanged until 1.0.

## Upgrading to 0.3.0

The empty top-level `collectors`, `antigaming`, and `gating` modules deprecated
in 0.2.0 are removed. Update any old dotted settings paths before upgrading:

| Removed path | Supported path |
|---|---|
| `evennia_plots.collectors.collect_thread_bonuses` | `evennia_plots.integrations.xp.collect_thread_bonuses` |
| `evennia_plots.collectors.collect_arc_bonuses` | `evennia_plots.integrations.xp.collect_arc_bonuses` |
| `evennia_plots.antigaming.sweep` | `evennia_plots.integrations.antigaming.sweep` |
| `evennia_plots.gating.resolve_xp_multiplier` | `evennia_plots.integrations.gating.resolve_xp_multiplier` |

The installation examples above already use these supported paths.

Thread bonus collection uses `evennia_xp.gating.resolve_xp_multiplier`, so a
host may compose its own XP policy with the plots resolver. Delegate to the
plots resolver to preserve per-arc scaling. Existing arc pauses still suppress
thread bonuses before collection.

## Theming

Every colour in this contrib's stylesheet is a shared `--evennia-color-*`
token with its usual colour as the fallback, so the pages look the same
until your game sets one. Set them on `:root` in your own stylesheet to
retheme these pages along with the other contribs'. The token list and an
example are in [evennia-accessibility's README](../../utils/evennia_accessibility/README.md#theme-tokens).

## Guide pages

The `guides/` directory holds player guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `plots`,
`glossary-arc`, `glossary-thread`, `glossary-held`. They explain the system to players in general terms, without
exact numbers, and link only to pages this contrib or its required dependencies
ship. With evennia-guides installed they appear on its web guide; without it
they're ignored. To restate one for your game, add a page with the same key to
`GUIDES_DIRS`.
