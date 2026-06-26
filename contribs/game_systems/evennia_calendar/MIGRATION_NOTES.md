# Migration Notes — evennia_calendar v0.1.0

This document records divergences from the original source implementation that
adopters should be aware of when upgrading or integrating.

## Namespace changes

If you are migrating from a local calendar implementation, update all imports
to point to `evennia_calendar.*` equivalents:

| Was (local game module) | Now (contrib) |
|---|---|
| `<game>.calendar.models` | `evennia_calendar.models` |
| `<game>.calendar.signals` | `evennia_calendar.signals` |
| `<game>.calendar.scheduler` | `evennia_calendar.scheduler` |
| local `CmdCalendar` | `evennia_calendar.commands.CmdCalendar` |
| local `CmdRsvp` | `evennia_calendar.commands.CmdRsvp` |
| local calendar views | `evennia_calendar.views.*` |
| Template `website/calendar_month.html` | `evennia_calendar/calendar_month.html` |

## Commands — merged module

`CmdCalendar` and `CmdRsvp` were separate source files (`commands/events/calendar.py`
and `commands/events/rsvp.py`). They are merged into a single
`evennia_calendar/commands.py` for packaging simplicity.

## Commands — staff lock

The source used a module-level `_is_staff(character)` function that read a
project-specific settings key. The contrib reads `CALENDAR_STAFF_LOCK`
(default `"cmd:perm(Builder)"`), matching the `BOARDS_STAFF_LOCK` /
`SCENES_STAFF_LOCK` pattern from sibling contribs.

## Commands — web URL helper

The source imported `world.utils.urls.absolute_web_url`. The contrib vendors a
local `_event_web_path(pk)` helper that reads `getattr(settings, "SITE_URL", "")`.
Set `SITE_URL = "https://yourdomain.com"` to get absolute URLs in in-game output.

## Commands — accessibility import

The source imported `world.utils.accessibility.uses_screenreader` directly. The
contrib uses a soft import shim:

```python
try:
    from evennia_accessibility.utils import uses_screenreader
except ImportError:
    def uses_screenreader(_): return False
```

This makes `evennia-accessibility` optional at the command level (only required
for the `[web]` extra).

## Forms — base classes

The source used `CoVBaseModelForm` / `CoVBaseForm` base classes from the game's
`web/website/forms.py`. The contrib ships its own `AccessibleModelForm` /
`AccessibleForm` (same Bootstrap 4 + ARIA logic, no external dependency).

## Views — URL namespace

All `{% url 'calendar-...' %}` references in templates are now
`{% url 'evennia_calendar:calendar-...' %}` (namespaced app URLs). Update any
custom templates that reference the old unnamespaced routes.

## Views — authoring mixin

The source used `CoVAuthoringMixin` from `web.website.views._authoring`. The
contrib ships `CalendarAuthoringMixin` from `evennia_calendar.authoring` with
identical behaviour.

## Templates — partials removed

The source templates used game-specific partials:
- `website/partials/_form_errors.html`
- `website/partials/_form_field.html`
- `website/partials/_form_actions.html`
- `website/partials/_pagination.html`
- `website/partials/_empty_state.html`

The contrib templates inline equivalent Bootstrap 4 markup. Games that have
these partials can re-introduce them by overriding the contrib templates.

## No `evennia-links` dependency

The source calendar was the *target* of soft-reference bridges owned by other
apps (`world/links/`, evennia-boards, etc.). The contrib does not import from
`evennia-links` at all. Consumers who create soft-reference bridges to calendar
objects are responsible for registering their own cleanup signals.

## CalendarMaintenanceScript — manual hook required

The source registered `ensure_calendar_script_running()` via a project-level
server-start hook. The contrib cannot auto-register this because Evennia has no
server-start signal. Adopters must add the call to `at_server_start()` manually.
See `README.md` for the snippet.
