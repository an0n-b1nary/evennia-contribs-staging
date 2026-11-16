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
- **Shared web staff policy:** HTTP staff checks use `evennia-links>=0.8.15`; `CALENDAR_STAFF_LOCK` remains for in-game authoring.

## Requirements

### Core (models + commands)

```
evennia>=6.0
evennia-links>=0.8.15
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
from evennia_calendar.commands import CmdCalendar, CmdCluster, CmdRsvp

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        ...
        self.add(CmdCalendar)
        self.add(CmdCluster)
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
| `CALENDAR_STAFF_LOCK` | `"cmd:perm(Builder)"` | Evennia lock expression for in-game/calendar authoring (event toggle, cluster lock, tag creation). HTTP staff checks use `EVENNIA_WEB_STAFF_LOCK`. |
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
2. Staff locks the cluster: `+cluster/lock <id>`.
3. Players submit ranked preferences: `+cluster/rank <cid>=<eid1>,<eid2>,...`.
4. The scheduler runs `run_cluster_lottery()` 72 h before the earliest event.
5. Each player is seated in their highest-ranked event with remaining capacity.
6. Players not seated receive a `CLUSTER_RANK1` priority token.

## Personal calendar and cluster commands

Upgrading to 0.6: run `evennia migrate evennia_calendar`. Migration `0004`
updates the cluster field's help text for the new commands; existing event,
cluster, RSVP and token data and IDs are preserved.

`+calendar/mine` lists every upcoming, non-cancelled event the character hosts
or has a current RSVP for. It shows Host, RSVP status and waitlist position,
without duplicates when a host also attends. Released RSVPs are excluded.

Register `CmdCluster` beside `CmdCalendar` and `CmdRsvp`. `+cluster <cid>` views
a cluster; `/new <title>`, `/add <eid>=<cid>`, `/remove <eid>` and staff-only
`/lock <cid>` manage it. Players use `/rank <cid>=<eid>,<eid>,...`,
`/mine <cid>` and `/withdraw <cid>`. An application creates no event RSVP until
the draw seats the player, so pending applications appear through
`+cluster/mine`, rather than in `+calendar/mine`. After seating, the assigned
event appears in the personal calendar and uses the ordinary `+rsvp` controls.

`+rsvp/tokens` lists priority tokens; `/redeem <eid>` earmarks an EVENT token
for the lottery. Cluster tokens are still redeemed automatically by the draw.
Commands accept unique switch prefixes, but the retired `/token` spelling is
explicitly refused. The former cluster forms on Calendar and RSVP, stacked
switches and unknown or ambiguous switches are refused as well.

## Priority tokens

| Scope | When issued | When redeemed |
|---|---|---|
| `EVENT` | Player not selected in a single-event lottery | Earmarked for a specific staff event via `+rsvp/redeem <eid>` — guaranteed pre-seating before the random draw |
| `CLUSTER_RANK1` | Player unseated in a cluster draw | Automatically applied at the next cluster lottery for the same cluster — guaranteed first-preference seating |

## Signals

All signals are exported from `evennia_calendar` (safe to import at app-load time):

| Signal | Sent on | Kwargs |
|---|---|---|
| `event_created` | new CalendarEvent saved | `event` |
| `event_cancelled` | event soft-cancelled | `event` |
| `event_starting_soon` | 24 h reminder sweep | `event` |
| `lottery_drawn` | lottery completed for an event | `event`, `selected`, `lottery_entered_remaining` |
| `lottery_selected` | individual player selected | `event`, `rsvp` |
| `lottery_confirmation_expired` | unconfirmed selection released | `event`, `rsvp` |
| `rsvp_status_changed` | RSVP status transition | `rsvp`, `old_status`, `new_status` |
| `waitlist_promoted` | waitlisted player offered a seat | `event`, `rsvp` |
| `cluster_drawn` | cluster lottery completed | `cluster`, `seated_count`, `unseated_count` |
| `cluster_seat_assigned` | individual player assigned to event | `cluster`, `cluster_rsvp`, `rsvp`, `rank_achieved` |

## Player notices

The calendar tells players about their own RSVPs, with no wiring:

- **Drawn** in a lottery or seated by a cluster draw (`lottery_selected`,
  `cluster_seat_assigned`), with the confirmation deadline.
- **Given a place** from the waitlist when someone cancels (`waitlist_promoted`
  to confirmed), or **offered one** by a host's `+rsvp/ping` (to invited).
- **Invited** by a host, with `+rsvp/invite` or the web invite form.
- **Reminded** of an event they're confirmed for, once per RSVP, when the sweep
  fires `event_starting_soon`.

With Inbox installed, register the production source in host settings:

```python
LINKS_NOTICE_SOURCES = {
    "calendar": "evennia_calendar.integrations.notices.CalendarNoticeSource",
}
```

Install `evennia-calendar[inbox]` (Inbox>=0.1.1) and wire Inbox's own commands,
URLs and maintenance as its README describes. Routine notices arrive quietly;
source preferences support immediate, login summary and off. Lottery selections
and sought waitlist offers default immediate and cannot be disabled entirely.
They remain in **awaiting your decision** after reading until confirmation,
decline, expiry or cancellation. Ordinary invitations are clearable. Reading or
clearing an alert never changes its RSVP. Text and counts recheck current
ownership, status, deadline and ignore policy; only the selected character's
notices appear on the website. Display text uses current event data and does not
copy historical sender/account names into the inbox.

Without Inbox, when disabled, or when the Calendar source is omitted from the
registry, standalone delivery remains immediate when connected and pending until
puppet otherwise. A configured but broken backend/source remains pending rather
than delivering twice. Each reminder still has one persistent RSVP receipt.
Source receipts survive clearing/pruning Inbox, disabling it, uninstalling it,
and reinstalling it. Already delivered/transferred events never replay.

### Upgrade and pending notices

Run migrations, then `evennia transfer_calendar_notices`. It processes one
bounded page (default 100) and reports transferred, held, invalid, retry and
continuation counts. Repeat to finish a pass; the Calendar maintenance sweep and
an optional Inbox preparation hook continue it automatically. The hook transfers
only the actual selected character before their summary. No database access
occurs in app startup registration.

Migration 0005 preserves source row IDs, message history, and reminder receipts.
Legacy system notices bind only when timestamp/status/recipient evidence proves
the current generation. Old human invitations/offers lack reliable sender IDs;
ambiguous generations and unknown actors remain held without text, counts or
acknowledgement, even if Inbox is disabled or absent. Source history is retained;
held records retire safely when their subject becomes invalid. Hosts must not
infer their sender from a current event owner or stored display name.

The positional API `notify(rsvp, kind, message)` remains available. Shipped human
producers additionally pass `origin="invitation"` or `"waitlist_offer"` and the
actual `actor`. Custom human callers without provenance remain pending for
privacy. New system origins are `lottery`, `seated` and `reminder`. Use RSVP's
`save`, `confirm` and `release`; bulk status/character updates bypass generation
tracking. A stale instance cannot overwrite a newer transition; reload and retry.
A standalone socket failure is recorded as uncertain and does not automatically
retry; the content and receipt stay available for host diagnosis. Disposable
guests receive only connected hints and create no retained notice records.

## Map tile overlay (optional partner: evennia-maps)

Install `evennia-maps` alongside this contrib and mapped rooms show what is about to happen
there. `CalendarConfig.ready()` connects `evennia_calendar.integrations.maps.provide` to the
map's `collect_tile_overlays` signal — no settings, no wiring. Set `CALENDAR_MAPS_APP_LABEL`
if your game registers the maps app under a different label.

```python
{"upcoming_events": {room_id: [{"id": ..., "title": ...}, ...]}}   # soonest first
```

Two queries for the whole grid. An event has no room of its own: it reaches the map only
once a `Scene` is linked to it via `SceneCalendarLink`, so the scenes app is resolved
through `CALENDAR_SCENES_APP_LABEL` exactly as the soft-ref cleanup hook already resolves
it. With `evennia-scenes` absent the overlay is empty.

The map overlay is public: player and staff renders receive the same upcoming events.
``is_staff_event`` selects lottery RSVP mode rather than visibility. The
calendar's authoring flows still enforce the anti-favoritism pre-invite rule.


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

## Theming

Every colour in this contrib's stylesheet is a shared `--evennia-color-*`
token with its usual colour as the fallback, so the pages look the same
until your game sets one. Set them on `:root` in your own stylesheet to
retheme these pages along with the other contribs'. The token list and an
example are in [evennia-accessibility's README](../../utils/evennia_accessibility/README.md#theme-tokens).

## Guide pages

The staff-only [`calendar-staff`](guides/calendar-staff.md) page covers staff tasks, command permissions, safe changes, privacy and review queues. It stays readable by guide staff before player systems are revealed.

The `guides/` directory holds player and staff guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `calendar`. They
explain the system to players in general terms, without exact numbers, and link
only to pages this contrib or its required dependencies ship. With
evennia-guides installed they appear on its web guide; without it they're
ignored. To restate one for your game, add a page with the same key to
`GUIDES_DIRS`.

Compatible legacy duplicates and a replay of their current system producer use
one deterministic canonical source record, independent of migration order.
Its delivery, suppression or uncertain-attempt receipt governs every alias
even after Inbox removal. Source-row counts can therefore include duplicate
alias acknowledgements while retaining one Inbox event.

New guest notices and per-guest continuation cursors remain transient. Existing
pre-upgrade guest source rows are preserved and can be acknowledged once by
connected-only delivery, with fresh RSVP/event/recipient/generation and ignore
checks. An offline guest is never falsely acknowledged; an uncertain socket
attempt stays recorded on the existing canonical source row without replay.

Any proven member's completed or uncertain source receipt governs the compatible
transition, including mixed pre-upgrade queues where a later duplicate was
already delivered. Original delivered timestamps and frozen envelopes remain
unchanged. A configured-source failure preserves the pending outbox while its
backend savepoint rolls back partial Inbox data and immediate hints; repair the
configuration and repeat transfer to resume delivery.
