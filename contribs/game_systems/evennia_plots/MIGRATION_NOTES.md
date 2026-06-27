# Migration Notes — evennia-plots

This document records intentional divergences between `evennia-plots` and the
source MUSH project from which it was extracted, along with guidance for
downstream games adopting the contrib.

---

## 1. Fresh `0001_initial` replaces six incremental migrations

The source project accumulated six incremental migrations over the history of
the plots system. `evennia-plots` ships a single fresh `0001_initial` whose
end state is shape-equivalent to applying all six source migrations in order.

**If you are migrating from the source project**, run:

```bash
python manage.py migrate evennia_plots --fake-initial
```

after confirming that the DB schema already matches `0001_initial`.

---

## 2. Bridges and `PlotBonusCredit` relocated from `world/links/` into `evennia_plots/models.py`

In the source project, `ScenePlotLink`, `PlotCalendarLink`, `PlotBoardLink`, and
`PlotBonusCredit` lived in a shared cross-domain `world/links/` app. The source
project's domain-island rule forbids `world/plots/` from importing
`world/links/` directly, so the bridges were colocated in the hub.

`evennia-plots` cannot ship with that hub dependency. The bridges are
**relocated into `evennia_plots/models.py`** — the same relocation pattern
`evennia-lore` uses for its scene/thread/board bridges.

---

## 3. `ScenePlotLink.scene` and `PlotBoardLink.post` converted to integer soft-refs

The source project used hard ForeignKeys to the scenes and boards apps. These
have been converted to integer soft-reference fields (`scene_id`, `post_id`) so
that `evennia-plots` installs without requiring `evennia-scenes` or
`evennia-boards`.

**`PlotBoardLink` gains `is_ic_post`:** Because the `post__board__board_type`
traversal can no longer be performed at query time, the IC/OOC classification
is captured as a boolean at link-creation time via `PlotBoardLink.create_link()`.
The +1 IC-post bonus check in `_compute_bonus_xp()` now reads
`board_links.filter(is_ic_post=True)` rather than traversing the FK.

---

## 4. XP glue bundled in `evennia-plots` (forced divergence from source layout)

In the source project the XP machinery is split across three modules outside
`world/plots/`:

| Source location | `evennia-plots` location |
|---|---|
| `world/utils/xp_gating.py` | `evennia_plots/gating.py` |
| `world/xp/collectors.py` (thread/arc slice) | `evennia_plots/collectors.py` |
| `world/xp/antigaming.py` (thread slice) | `evennia_plots/antigaming.py` |
| `world/links/models.py::PlotBonusCredit` | `evennia_plots/models.py` |

The source keeps these outside `world/plots/` because its domain-island rule
forbids `world/plots/` importing `world/xp/`. The contrib does not have this
constraint — `evennia_xp` is an explicit optional dependency — so all XP glue
ships with `evennia-plots`.

The implementations are straight copies with import paths swapped. Any future
divergence in the source should be manually mirrored here.

---

## 5. `evennia-xp` is optional (`[xp]` extra)

`PlotBonusCredit` (the eligibility table), `gating.py` (the multiplier
resolver), and the core domain models have **no dependency on `evennia-xp`**. Only
`collectors.py` and `antigaming.py` import `evennia_xp.models.XPLog`, and they
do so with **function-local imports**, so the modules can be imported even when
`evennia-xp` is not installed. The collectors/sweep simply raise an `ImportError`
at call time if `evennia_xp` is absent.

Register the XP seams in your settings only when `evennia-xp` is installed:

```python
# settings.py
XP_MULTIPLIER_RESOLVER = "evennia_plots.gating.resolve_xp_multiplier"

XP_COLLECTORS = [
    ("thread_bonus", "evennia_plots.collectors.collect_thread_bonuses"),
    ("arc_bonus",    "evennia_plots.collectors.collect_arc_bonuses"),
]

XP_ANTIGAMING_SWEEPS = [
    "evennia_plots.antigaming.sweep",
]
```

---

## 6. Anti-gaming Job-ticket side not shipped

The source project's anti-gaming sweep is triggered by a staff Jobs ticket
(`+request/review`) after each XP batch. That ticket-side hook is
game-specific (it calls into the source's Jobs system with project-specific
messaging). It is intentionally omitted from the contrib. See the stub comment
in `antigaming.py` for where to add your own post-flag hook.

---

## 7. Projection slice intentionally omitted

The source project includes a `project_for_character()` helper that computes a
character's projected plot-bonus XP over a rolling window. This is heavily tied
to the source's XP display and character-sheet views. It is omitted from the
contrib (matching `evennia-xp`, which similarly omitted game-specific projection
logic). Implement your own by calling `collect_thread_bonuses(window_end)` and
summing the yielded `Award` objects filtered to a single `character_id`.

---

## 8. Partner app labels

`apps.py` reads three settings to locate partner app models for soft-ref cleanup:

| Setting | Default |
|---|---|
| `PLOTS_SCENES_APP_LABEL` | `"scenes"` |
| `PLOTS_CALENDAR_APP_LABEL` | `"calendar"` |
| `PLOTS_BOARDS_APP_LABEL` | `"boards"` |

Override these if your game uses different app labels for scenes, calendar
events, or board posts.
