# evennia-calendar

Event calendar system for Evennia games. Provides in-game commands (`+calendar`, `+rsvp`), a month/list web view, a Django REST Framework API, and a ranked-choice cluster lottery with priority tokens.

## Features

- **Three RSVP modes:** open (no cap), capped (first-come-first-serve + optional waitlist), and staff lottery (random draw 72 h before the event)
- **EventCluster:** groups related parallel events for ranked-choice RSVP — players rank preferences, lottery seats each player in their highest-ranked event with capacity
- **Priority tokens:** players not selected in a lottery draw receive a consolation token that guarantees pre-seating in the next applicable lottery
- **Anti-favoritism guard:** `is_staff_event` flag blocks pre-inviting on both commands and web views
- **Thematic tags:** staff-managed canonical tag list prevents name drift
- **Mutual exclusion:** pairs of events where a player can only attend one
- **Web UI:** month grid, list view (with filters), detail, cluster, and all authoring views
- **REST API:** `CalendarEventViewSet` with date/emphasis/staff-event filters
- **Accessibility-aware commands:** optional `evennia-accessibility` integration for screenreader mode
- **No `evennia-links` dependency:** first `game_systems` contrib with only `evennia>=6.0` as core dependency

## Requirements

### Core (models + commands)

```
evennia>=6.0
```

### Web + API (`[web]` extra)

```
evennia-accessibility>=0.1  (optional — screenreader shim included if absent)
djangorestframework>=3.14
django-filter>=23
```

## Installation

### 1. Install the package

```bash
pip install evennia-calendar          # core only
pip install "evennia-calendar[web]"   # + web UI and REST API
```

### 2. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    ...
    "evennia_calendar",
]
```

### 3. Run migrations

```bash
evennia migrate
```

### 4. Wire the maintenance script

Add to your game's `at_server_start()` (typically in `server/conf/serversessionhandler.py` or a custom hook):

```python
from evennia_calendar.scheduler import ensure_calendar_script_running

def at_server_start():
    ensure_calendar_script_running()
```

**Why manual?** Evennia has no server-start signal, so the `CalendarMaintenanceScript` that runs lottery draws, RSVP expiry, token issuance, and 24 h reminders must be started manually from this hook. The script is persistent (survives reboots once created) — `ensure_calendar_script_running()` is idempotent and safe to call repeatedly.

### 5. Wire the commands

```python
# In your default_cmdsets.py
from evennia_calendar.commands import CmdCalendar, CmdRsvp

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        ...
        self.add(CmdCalendar)
        self.add(CmdRsvp)
```

### 6. Wire the web views (optional)

```python
# In your game's urls.py
from django.urls import include, path

urlpatterns = [
    ...
    path("calendar/", include(("evennia_calendar.urls", "evennia_calendar"))),
]
```

### 7. Wire the REST API (optional)

```python
# In your game's api urls.py
from evennia_calendar.api.urls import urlpatterns as calendar_api_urls

urlpatterns = [
    ...
    *calendar_api_urls,
]
```

## Settings

| Setting | Default | Description |
|---|---|---|
| `CALENDAR_STAFF_LOCK` | `"cmd:perm(Builder)"` | Evennia lock expression for staff-level calendar access (event toggle, cluster lock, tag creation). Use `cmd:perm(Builder)` or a custom lock expression. |
| `SITE_URL` | `""` | Base URL for absolute web links in in-game `\|lu...\|le` MXP links (e.g. `"https://mygame.example.com"`). Empty string produces relative paths (webclient-only). |

## Soft-reference contract

`CalendarEvent`, `EventCluster`, and other models hold integer `event_id` / `cluster_id` soft-references for use by consuming apps (boards, plots, etc.). These are `PositiveBigIntegerField` values — **not** `ForeignKey`s — so they survive cross-app isolation.

Consuming apps that create soft-reference bridges to calendar objects are responsible for registering their own cleanup signals when events are cancelled or deleted. See `evennia_boards` for an example of how `connect_soft_ref_cleanup` is used.

## RSVP modes

| Mode | When | Behaviour |
|---|---|---|
| **Open** | No participant cap | RSVP → immediately confirmed |
| **Capped** | Participant cap set | Confirmed up to cap, then waitlisted. Host can pre-invite via `+rsvp/invite` or web. |
| **Lottery** | `is_staff_event=True` | RSVP enters the draw. Draw runs 72 h before the event. Priority token holders are seated first, then random selection fills remaining seats. Selected players confirm within 24 h or are released. Non-selected players receive a priority token. |

## Cluster RSVP

A cluster groups parallel events (same `scheduled_time`) for ranked-choice RSVP:

1. Staff creates events and a cluster, then adds events to the cluster.
2. Staff locks the cluster: `+calendar/cluster/lock <id>`.
3. Players submit ranked preferences: `+rsvp/cluster <cid>=<eid1>,<eid2>,...`.
4. The scheduler runs `run_cluster_lottery()` 72 h before the earliest event.
5. Each player is seated in their highest-ranked event with remaining capacity.
6. Players not seated receive a `CLUSTER_RANK1` priority token.

## Priority tokens

| Scope | When issued | When redeemed |
|---|---|---|
| `EVENT` | Player not selected in a single-event lottery | Earmarked for a specific staff event via `+rsvp/token/use <eid>` — guaranteed pre-seating before the random draw |
| `CLUSTER_RANK1` | Player unseated in a cluster draw | Automatically applied at the next cluster lottery for the same cluster — guaranteed first-preference seating |

## Signals

All signals are exported from `evennia_calendar` (safe to import at app-load time):

| Signal | Sent on | Kwargs |
|---|---|---|
| `event_created` | new CalendarEvent saved | `event` |
| `event_cancelled` | event soft-cancelled | `event` |
| `event_starting_soon` | 24 h reminder sweep | `event` |
| `lottery_drawn` | lottery completed for an event | `event`, `selected_pks` |
| `lottery_selected` | individual player selected | `event`, `rsvp` |
| `lottery_confirmation_expired` | unconfirmed selection released | `event`, `rsvp` |
| `rsvp_status_changed` | RSVP status transition | `rsvp`, `old_status`, `new_status` |
| `waitlist_promoted` | waitlisted player offered a seat | `event`, `rsvp` |
| `cluster_drawn` | cluster lottery completed | `cluster`, `results` |
| `cluster_seat_assigned` | individual player assigned to event | `cluster`, `cluster_rsvp`, `event` |

## Programmatic API

```python
from evennia_calendar.models import CalendarEvent, EventCluster
from evennia_calendar.scheduler import (
    run_lottery,
    run_cluster_lottery,
    expire_unconfirmed,
    issue_post_event_tokens,
    promote_waitlist,
    ensure_calendar_script_running,
)

# Create an event
event = CalendarEvent.create_event(
    creator=character,
    title="The Grand Tournament",
    scheduled_time=datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc),
    emphasis=CalendarEvent.Emphasis.COMBAT,
    participant_cap=20,
    is_staff_event=True,
)

# Run the lottery manually (normally handled by CalendarMaintenanceScript)
run_lottery(event)
```
