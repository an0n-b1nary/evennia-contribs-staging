# evennia-xp

Registry-driven weekly XP batch engine for [Evennia](https://www.evennia.com) games.

Ships the **engine** — ledger models, award service, batch runner, `+xp`
command — not the game-specific sources. You write the collectors that read
your game's data and yield `Award` objects; `evennia-xp` handles idempotency,
aggregation, scheduling, and the web/API surface.

---

## Features

- **`XPLog` / `CharacterXP`** — integer-keyed ledger + aggregate models (no
  `ObjectDB` FK; install without any other Evennia model dependency).
- **`record_xp()`** — idempotent single write path with F()-expression
  `CharacterXP` aggregation and `xp_awarded` signal.
- **Registry-driven batch** — `XP_COLLECTORS`, `XP_ANTIGAMING_SWEEPS`,
  `XP_POST_BATCH_HOOKS` settings; `XP_MULTIPLIER_RESOLVER` for arc/DOWNTIME
  scaling.
- **`XPBatchScript`** — Evennia Script that runs the batch every Monday at
  00:00 UTC; idempotent across server restarts.
- **`CmdXp`** — `+xp`, `+xp/log`, `+xp/sources`, `+xp/grant` with
  `XP_STAFF_LOCK` and optional `evennia-accessibility` screen-reader support.
- **Web + API** (`[web]` extra) — `XPSummaryView` (self-only balance + log)
  and `XPLogViewSet` (DRF read-only self-only).
- **`run_xp_batch`** management command for backfills and debugging.

---

## Quick start

### 1. Install

```bash
pip install evennia-xp              # core only
pip install "evennia-xp[web]"       # + web/API surface
```

### 2. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS += [
    "evennia_xp",
    # If using [web]:
    # "evennia_accessibility",
]
```

### 3. Migrate

```bash
evennia migrate evennia_xp
```

### 4. Register the Script

In your game's `at_server_start()`:

```python
from evennia_xp.scripts import ensure_xp_batch_script_running
ensure_xp_batch_script_running()
```

### 5. Add the command

```python
# In your CharacterCmdSet or AccountCmdSet
from evennia_xp.commands import CmdXp
self.add(CmdXp)
```

### 6. Write a collector and register it

```python
# myapp/xp_collectors.py
from decimal import Decimal
from evennia_xp.batch import Award
from evennia_xp.models import XPLog

def collect_my_sessions(window_end):
    from datetime import timedelta
    from myapp.models import MySession

    window_start = window_end - timedelta(days=7)
    sessions = MySession.objects.filter(
        ended_at__gt=window_start,
        ended_at__lte=window_end,
        xp_awarded=False,
    )
    for session in sessions:
        yield Award(
            character_id=session.character_id,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=session.pk,
            multiplier=Decimal("1.0"),
            reason="RP session",
        )
```

```python
# settings.py
XP_COLLECTORS = [
    ("rp_session", "myapp.xp_collectors.collect_my_sessions"),
]
```

That's it — the batch will call your collector every Monday and write XPLog
rows via `record_xp()`.

---

## Settings reference

| Setting | Default | Description |
|---|---|---|
| `XP_COLLECTORS` | `[]` | List of `(key, "dotted.path")` pairs. Each function signature: `fn(window_end) → Iterable[Award]`. |
| `XP_ANTIGAMING_SWEEPS` | `[]` | List of dotted paths. Each: `sweep(window_end)`. Called before collectors. |
| `XP_POST_BATCH_HOOKS` | `[]` | List of dotted paths. Each: `hook(window_end, awards, week_label)`. Called after writes. |
| `XP_MULTIPLIER_RESOLVER` | `None` | Dotted path to `fn(source, *, thread, room, character) → Decimal`. Returns 1.0 when unset. |
| `XP_STAFF_LOCK` | `"cmd:perm(Builder)"` | Evennia lock expression for `+xp/grant` and web staff checks. |

---

## The `Award` namedtuple

```python
from evennia_xp.batch import Award

Award(
    character_id=int,       # ObjectDB pk of the recipient
    amount=Decimal,         # XP to award (base × multiplier, already applied)
    source_type=str,        # XPLog.SourceType value, e.g. "rp_session"
    source_ref_id=int,      # PK of the upstream row (for idempotency)
    multiplier=Decimal,     # Multiplier applied (for audit in XPLog)
    reason=str,             # Human-readable note stored in XPLog.reason
)
```

Idempotency: `record_xp()` uses `(source_type, source_ref_id)` as a unique
key for all non-MANUAL_GRANT awards. Re-running the batch for the same week
is a safe no-op.

---

## The multiplier resolver seam

If your game has arc-based XP scaling, register a resolver:

```python
# settings.py
XP_MULTIPLIER_RESOLVER = "myapp.xp_gating.resolve_xp_multiplier"
```

```python
# myapp/xp_gating.py
from decimal import Decimal

def resolve_xp_multiplier(source, *, thread=None, room=None, character=None):
    arc = get_current_arc()   # your game's arc lookup
    if arc and arc.is_downtime:
        return Decimal("0.5")
    return Decimal("1.0")
```

The resolver is called by `evennia_xp.gating.resolve_xp_multiplier()`, which
degrades to 1.0 if the setting is unset or the resolver raises.

---

## XP spending

`+spend` and `+upgrade` are game-specific (they tie into your ability/stat
system). Implement them as separate commands in your game and link them to
`CharacterXP.total_spent` / `CharacterXP.current_balance`. The `record_xp()`
service only handles earning; spending is a plain `CharacterXP.objects.update()`
in the opposite direction.

---

## Web / API (requires `[web]` extra)

```python
# urls.py
from django.urls import include, path
urlpatterns += [
    path("xp/", include("evennia_xp.urls")),          # website
    path("api/v1/", include("evennia_xp.api.urls")),  # DRF
]
```

- `GET /xp/` — `XPSummaryView` — balance card + by-source breakdown + paginated log. Requires login + active puppet.
- `GET /api/v1/xp-log/` — `XPLogViewSet` — returns only the requesting character's rows.

---

## Management command

```bash
evennia run_xp_batch                        # last completed week
evennia run_xp_batch --week=2026-W18        # specific week
evennia run_xp_batch --dry-run              # compute, don't write
evennia run_xp_batch --source=rp_session    # one collector only
```

---

## Signals

```python
from evennia_xp.signals import xp_awarded, xp_batch_completed

# xp_awarded — fired per XPLog row written
# kwargs: character_id (int), xplog (XPLog), source_type (str)

# xp_batch_completed — fired after run_weekly_batch completes
# kwargs: summary (BatchSummary), week (str)
```
