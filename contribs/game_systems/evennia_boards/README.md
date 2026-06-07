# evennia-boards

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Classic MUSH bulletin board system for [Evennia](https://www.evennia.com/) games.
Players read and post to named boards in-game (`+bb`/`+board`) and optionally via
a web interface. Login notifications alert accounts to unread posts on subscribed
boards. IC boards integrate with [evennia-xp](../evennia_xp/) for cutscene XP awards.

---

## What's included

| Component | Purpose |
|---|---|
| `Board`, `Post`, `Subscription` models | Core board storage |
| `PostVersion(AbstractVersion)` | Append-only edit history |
| `PostCalendarLink` | Optional soft-ref bridge to calendar events |
| `CmdBoard` (`+bb` / `+board`) | Full in-game BBS command |
| Login listener | Auto-notifies subscribed accounts of unread posts on login |
| `post_created`, `board_unread_notified` signals | Hookable events |
| Website surface (`[web]`) | 5 CBVs, accessible forms, Bootstrap 4 templates |
| DRF API (`[web]`) | Read-only `BoardViewSet` + `PostViewSet` with cursor pagination |
| `integrations/xp.py` (`[xp]`) | Cutscene XP collector + anti-gaming sweep |

---

## Dependencies

**Hard:** `evennia>=6.0`, `evennia-links>=0.2` (provides `AbstractArchived`, `AbstractVersion`, `AbstractAuthoredLink`, `connect_soft_ref_cleanup`)

**Optional `[web]`:** `evennia-accessibility>=0.1`, `djangorestframework>=3.14`, `django-filter>=23`

**Optional `[xp]`:** `evennia-xp>=0.1`

---

## Installation

**Core** (models + commands, no web or XP deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_boards&egg=evennia_boards"
```

**With web UI and API:**

```
pip install -e "git+...&egg=evennia_boards[web]"
```

**With XP integration:**

```
pip install -e "git+...&egg=evennia_boards[xp]"
```

---

## Quickstart

### 1. Add to INSTALLED_APPS

`evennia_boards` must appear **after** `evennia_links` and **before** your game-specific apps:

```python
INSTALLED_APPS = [
    # ...evennia core apps...
    "evennia_links",
    "evennia_boards",
    # ...your apps...
]
```

### 2. Run migrations

```
evennia migrate
```

### 3. Add the command

In `commands/default_cmdsets.py`:

```python
from evennia_boards.commands import CmdBoard

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        super().at_cmdset_creation()
        self.add(CmdBoard)
```

Account-level read and subscription commands also work from AccountCmdSet.

### 4. Create your first board (in-game or Django admin)

```
+bb/create General=General discussion (OOC)
+bb/create Cutscenes=In-character narrative posts (IC)
```

Or create `Board` instances via Django admin.

### 5. Optional: web UI

Add to your game's `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    # ...
    path("boards/", include("evennia_boards.urls", namespace="evennia_boards")),
    path("api/boards/", include("evennia_boards.api.urls")),
]
```

---

## Settings reference

| Setting | Default | Purpose |
|---|---|---|
| `BOARDS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock expression for staff-only board actions |
| `BOARDS_CALENDAR_APP_LABEL` | `None` | App label to enable `PostCalendarLink` soft-ref cascade cleanup |
| `BOARDS_ANTIGAMING_REPORTER` | `None` | Dotted path to `callable(title, description)` for staff ticket creation on XP flag |

---

## XP integration

Requires `evennia-xp` and registration in settings:

```python
XP_COLLECTORS += [
    ("cutscene", "evennia_boards.integrations.xp.collect_cutscene_posts"),
]
XP_ANTIGAMING_SWEEPS += [
    "evennia_boards.integrations.xp.sweep_cutscene_spam",
]
```

Posts on IC-type boards earn 1 XP each (scaled by the active arc multiplier).
The sweep flags authors who post ≥ 3 IC posts within any 24-hour window. Flagged
posts are excluded from awards until staff review and clear the flag.

To forward flags to a staff ticket system (e.g. evennia-jobs):

```python
BOARDS_ANTIGAMING_REPORTER = "myapp.jobs.reporters.create_antigaming_job"
```

The callable receives `(title: str, description: str)`.

---

## Calendar soft-ref cleanup

When `BOARDS_CALENDAR_APP_LABEL` is set and that app is in `INSTALLED_APPS`,
`BoardsConfig.ready()` registers a cascade cleanup hook so that deleting a
calendar event also deletes all `PostCalendarLink` rows pointing to it:

```python
BOARDS_CALENDAR_APP_LABEL = "calendar"  # the app_label of your calendar model
```

---

## Login notifications

No game-side code is required. `BoardsConfig.ready()` connects
`_notify_board_subscriptions` to `SIGNAL_ACCOUNT_POST_LOGIN` with a
`dispatch_uid` for idempotence across server reloads. Accounts see a summary
of unread posts on their subscribed boards each time they log in.

---

## Board types

| Type | Value | XP-eligible |
|---|---|---|
| OOC | `"ooc"` | No |
| IC (cutscene) | `"ic"` | Yes (with `[xp]` integration) |

---

## Signals

```python
from evennia_boards.signals import post_created, board_unread_notified

# post_created(sender=Post, post=Post, board=Board)
post_created.connect(my_handler)

# board_unread_notified(sender=Account, subscriptions=QuerySet)
board_unread_notified.connect(my_handler)
```

---

## License

BSD 3-Clause. See [LICENSE](LICENSE).
