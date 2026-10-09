# evennia-links

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

Abstract base models and helpers for cross-system bridge ("link") models in
[Evennia](https://www.evennia.com/) games.

This package is the **shared hub** that domain contribs depend on. It ships
no tables of its own — only abstract Django models, small runtime helpers, and
a shared version-tracked text-editing mixin. The concrete bridge models that
connect your game's domain apps together live in your own game code (or in
downstream domain contribs like `evennia-scenes`, `evennia-plots`, etc.).

---

## What's included

| Name | Module | Purpose |
|---|---|---|
| `AbstractLink` | `links.py` | Minimal base: `created_at` + `create_link()` |
| `AbstractAuthoredLink` | `links.py` | Adds `created_by` / `created_by_name` audit block |
| `AbstractVersion` | `versioning.py` | Append-only version history for any text field |
| `AbstractArchived` + `ArchivedManager` | `archiving.py` | Soft-archive with default-manager filtering |
| `EditingMixin` | `editing.py` | EvEditor + difflib mixin for version-tracked text editing; pairs with `AbstractVersion` |
| `connect_on_ready` | `listeners.py` | Import-order-safe signal-registration helper |
| `connect_soft_ref_cleanup` | `softref.py` | Cascade compensation for integer soft-reference fields |
| `collect_dicts` | `collect.py` | Send a *collector* signal and merge every receiver's dict answer |
| `resolve_dotted` | `collect.py` | Import an object from a `"pkg.mod.attr"` settings path |

**Not yet included (deferred to a future release):** `NotificationDispatcher`.

---

## Installation

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/base_systems/evennia_links&egg=evennia_links"
```

Add to `INSTALLED_APPS` in your `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links"]
```

No migrations to run — this contrib ships only abstract models and a command mixin.

---

## Usage

### AbstractLink and AbstractAuthoredLink

Use `AbstractLink` when a bridge is created automatically (e.g. by a signal
listener). Use `AbstractAuthoredLink` when a player or staff member creates
the link and you want to audit who did it.

```python
from django.db import models
from evennia_links import AbstractLink, AbstractAuthoredLink

# System-created bridge (no human author):
class SessionSceneLink(AbstractLink):
    session = models.ForeignKey("rptracker.Session", on_delete=models.CASCADE,
                                related_name="scene_links")
    scene = models.ForeignKey("scenes.Scene", on_delete=models.CASCADE,
                              related_name="session_links")
    link_fields = ("session", "scene")

    class Meta(AbstractLink.Meta):
        unique_together = [("session", "scene")]

# Player-created bridge (records who linked it):
class ScenePlotLink(AbstractAuthoredLink):
    scene = models.ForeignKey("scenes.Scene", on_delete=models.CASCADE,
                              related_name="plot_links")
    thread = models.ForeignKey("plots.PlotThread", on_delete=models.CASCADE,
                               related_name="scene_links")
    link_fields = ("scene", "thread")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("scene", "thread")]
```

The `create_link()` classmethod is idempotent — it wraps `get_or_create`:

```python
# Returns (link_instance, created_bool):
link, created = ScenePlotLink.create_link(scene, thread, linked_by=character)
link, created = SessionSceneLink.create_link(session, scene)
```

Subclasses can override `create_link()` to add side-effects (fire a signal,
compute a derived field) while still calling `super()` for the get_or_create:

```python
@classmethod
def create_link(cls, scene, thread, linked_by=None):
    from myapp.signals import scene_linked_to_thread
    link, created = super().create_link(scene, thread, linked_by=linked_by)
    if created:
        scene_linked_to_thread.send(sender=cls, scene=scene, thread=thread)
    return link, created
```

### AbstractVersion

```python
from evennia_links import AbstractVersion

class PostVersion(AbstractVersion):
    parent = models.ForeignKey("boards.Post", on_delete=models.CASCADE,
                               related_name="versions")

    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]

# Snapshot before editing (pass OLD content):
PostVersion.create_version(post, old_content, editor=character)

# Roll back (creates a new version whose content is the old version's content):
PostVersion.rollback_to(post, version_number=3, editor=character)
```

### AbstractArchived

```python
from evennia_links import AbstractArchived

class Scene(AbstractArchived):
    title = models.CharField(max_length=200)
    # ...

# Default queryset excludes archived:
Scene.objects.all()           # only active scenes

# Include archived:
Scene.objects.include_archived().all()
Scene.all_objects.all()       # secondary manager, same result

# Archive / restore:
scene.archive(editor=character)
scene.unarchive()
```

### EditingMixin

Mix into `MuxCommand` subclasses to add EvEditor-based version-tracked editing
of any model text field. The version model class is supplied at call-time, so
`EditingMixin` works with any `AbstractVersion` subclass.

```python
from evennia_links import AbstractVersion, EditingMixin
from evennia.commands.default.muxcommand import MuxCommand

class PostVersion(AbstractVersion):
    parent = models.ForeignKey("boards.Post", on_delete=models.CASCADE,
                               related_name="versions")
    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]

class CmdPost(EditingMixin, MuxCommand):
    key = "+post"

    def func(self):
        sw = self.switches
        post = ...  # fetch the post
        version_cls = PostVersion

        if "edit" in sw:
            self.start_edit(post, field_name="content", version_model_class=version_cls)
        elif "history" in sw:
            self.view_versions(post, version_cls)
        elif "rollback" in sw:
            self.do_rollback(post, version_cls, version_number=int(self.args))
        elif "diff" in sw:
            self.view_diff(post, version_cls, version_number=int(self.args))
        elif "new" in sw:
            self.start_new_edit(callback=my_create_callback)
```

`EditingMixin` is imported lazily — bringing in `evennia_links` does **not**
import `EvEditor` until `EditingMixin` is first accessed, so model-only consumers
pay no extra import cost.

### connect_on_ready

```python
# In your AppConfig.ready():
from evennia_links import connect_on_ready

class MyAppConfig(AppConfig):
    def ready(self):
        from myapp.signals import thing_happened
        from myapp.listeners import on_thing_happened
        connect_on_ready(thing_happened, on_thing_happened)
```

Django deduplicates repeated `signal.connect()` calls for the same receiver,
so calling `connect_on_ready` multiple times (e.g. in tests) is safe.

### connect_soft_ref_cleanup

Cross-domain bridge models that link to **optional** partner apps should store
the foreign pk as a plain integer (`PositiveBigIntegerField`) rather than a
real Django `ForeignKey`. This avoids a DB dependency on the optional app —
the bridge table exists regardless of whether the partner is installed, and
the partner can be added or removed without migration conflicts.

The downside: Django's `CASCADE` rule no longer fires when the foreign entity
is hard-deleted. `connect_soft_ref_cleanup` restores that semantics at the
Python level by registering a `post_delete` receiver.

```python
from evennia_links import connect_soft_ref_cleanup

# In AppConfig.ready(), gate on the partner app being installed:
class MyTrackerConfig(AppConfig):
    def ready(self):
        from django.conf import settings
        from django.apps import apps

        label = getattr(settings, "MYAPP_SCENES_APP_LABEL", "scenes")
        if label in {a.split(".")[-1] for a in settings.INSTALLED_APPS}:
            from myapp.models import SessionSceneLink
            SceneModel = apps.get_model(label, "Scene")
            connect_soft_ref_cleanup(SceneModel, SessionSceneLink, "scene_id")
```

**Semantics:**
- Fires on **hard delete only.** Soft-archived records keep their link rows —
  the historical link survives the archive.
- Idempotent: registering with the same arguments multiple times is safe
  (Django deduplicates by `dispatch_uid`).

See the [Soft-dependency pattern](#soft-dependency-pattern) section below for
the companion pattern of gating the bridge's listener and migration.

### collect_dicts

Where `connect_on_ready` is for **notification** signals (fire and forget),
`collect_dicts` is for **collector** signals: one app asks a question and
merges the answers from however many apps happen to be installed.

This is what lets a feature aggregate data it does not own. The asking app
never imports the answering apps, so each side installs, uninstalls, and
ships independently — the answers simply stop arriving when a provider is
not present.

```python
# The asking app — owns the signal and the question:
from django.dispatch import Signal
collect_tile_overlays = Signal()   # kwargs: room_ids, staff

from evennia_links import collect_dicts
overlays = collect_dicts(
    collect_tile_overlays, sender=MapPlane, room_ids=room_ids, staff=staff
)
# -> {"has_active_scene": {12: True}, "upcoming_events": {12: [...]}, ...}

# A providing app — connects itself in its own gated AppConfig.ready():
def provide(sender, room_ids, staff, **kwargs):
    qs = Scene.objects.filter(room_id__in=room_ids)
    if not staff:                      # each provider keeps its OWN privacy rule
        qs = qs.filter(privacy__in=Scene.WEB_READABLE_PRIVACY)
    return {"has_active_scene": {s.room_id: True for s in qs}}
```

**Contract for providers:**

- Return a dict, or `None`/`{}` to contribute nothing.
- **Write disjoint top-level keys.** Receiver order is not guaranteed and must
  not matter; two providers claiming one key is a bug in the providers.
- A provider that raises, or returns a non-dict, is logged and skipped — it
  degrades its own contribution to absent and never breaks the asking request.
- **Keep each provider to one bulk query.** The signal is sent once per
  request, not once per item; a provider that queries per item reintroduces
  the N+1 the seam exists to avoid.

Privacy is the reason providers exist at all: only the owning app knows which
of its records a given viewer may see, so the filter must live on its side of
the seam rather than being re-encoded by the asking app.

### resolve_dotted

Imports the object at a dotted `"pkg.mod.attr"` path — the standard shape for
an optional hook configured in `settings.py`. Returns `None` for a `None`/empty
path; raises `ImportError` for a bad or dotless path, `AttributeError` if the
module has no such attribute.

```python
from evennia_links import resolve_dotted

hook = resolve_dotted(getattr(settings, "MYAPP_DISPLAY_HOOK", None))
if hook:
    line = hook(obj.pk)
```

Callers that treat the hook as *optional* should wrap the call and log-and-skip
on failure, so a game's misconfigured setting degrades that one feature instead
of crashing the command reading it.

### Web staff predicate

``is_staff_user(request)`` is the shared request-level staff decision for
contrib web views and APIs. It first checks the optional
``EVENNIA_WEB_STAFF_PREDICATE`` dotted callable; when unset it evaluates
``EVENNIA_WEB_STAFF_LOCK`` (default ``"cmd:perm(Builder)"``) through Evennia's
lock handler. A broken predicate or lock fails closed, and Django's
``user.is_staff`` flag is intentionally ignored. Existing per-contrib
``*_STAFF_LOCK`` settings continue to govern in-game commands and authoring;
games migrating HTTP staff checks should set the one web-wide setting instead.

---

## Bridge-ownership convention

When two contribs need to be linked, the bridge model belongs to the
**consuming / reactive contrib** — the one whose listener creates the row, or
whose feature consumes it.

**One-directional dependency rule:** bridges depend on the domain apps they
link; domain apps never import from the bridge layer. The arrow is always:

```
bridge model → domain app A
bridge model → domain app B
domain app A  ✗→ domain app B  (no direct dependency)
```

This means adding a new bridge never forces changes to the domain apps on
either end — only to the game code that wires them together.

### Soft-dependency pattern

When a bridge between two optional contribs should only exist if both are
installed, gate the bridge's registration in `AppConfig.ready()`:

```python
# myapp/apps.py
class MyAppConfig(AppConfig):
    def ready(self):
        from django.conf import settings
        if "evennia_scenes" in settings.INSTALLED_APPS:
            from myapp import bridges_scenes  # registers SceneLink + listener
        if "evennia_plots" in settings.INSTALLED_APPS:
            from myapp import bridges_plots   # registers PlotLink
```

Keep the bridge model itself in a separate module (`bridges_scenes.py`) so it
is only imported — and therefore only migrated — when the partner contrib is
present.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).

## Registered runtime controls and ownership caps

`evennia_links.runtime.register(name, default, validator=callable)` registers a
host setting as runtime-tunable, normally from `AppConfig.ready()`. `get(name)`
reads a ServerConfig override before the host setting and default. `set(name,
value, by=actor)` and `reset(name, by=actor)` validate, log the actor and send
`runtime_setting_changed` after commit; there is no process-local value cache.
Only registered names can be edited through `evennia_links.commands.CmdRuntime`
(`+runtime NAME=<JSON value>`, `+runtime/reset NAME`). Its staff lock defaults to
Builder and can be set with `LINKS_RUNTIME_STAFF_LOCK`.

`cap_contributions` in the same module is a robust collector signal. Providers
receive `character` and return disjoint provider keys, for example
`{"workshop": {"resources": 12, "money": 50}}`. `cap_raise(character, kind)` sums
nonnegative integer raises for that cap. Missing or broken providers contribute
nothing. The cap owner adds this raise to its base; providers never import it.

## Playable characters and period batches

`evennia_links.characters` is the one definition of "a player's characters"
for packages that pay or restrict players. `playable_characters(predicate=None)`
yields every character on any account's playable list once (offline ones
included), filtered by an optional `(character) -> bool` such as a host's
eligibility rule; `is_playable(character, predicate=None)` checks one character
without a sweep. `account_ids(character)` and `same_account(a, b)` back
same-account rules. Characters on no account (NPCs, props) belong to nobody.
The stored list is read directly, so sweeps don't load every account.

`web_character(user, roster_only=False)` is the character a web request acts
as. A website visitor need not be connected in-game, so a live puppet is a
preference rather than a requirement: a live puppet on the account's playable
list wins, then any other live puppet (a staffer playing an NPC) unless
`roster_only`, then the account's last puppet if it is on the list, then the
first character on the list. Anonymous users and accounts with nothing to play
resolve to `None`. Web contribs use it for their `get_character_id(user)`;
pass `roster_only=True` where the identity pays or records the character.

`evennia_links.periodic` serves weekly (or staff-shortened) batch scripts.
`period_key(seconds)` labels the most recently completed Monday-anchored
period (ISO weeks for the weekly default). `advance(state, period, run,
paused=False)` queues each new period once and calls `run(period, ids)`, which
pays everyone when `ids` is None and returns the ids that failed. Only those
retry, with exponential backoff (5 minutes doubling to 6 hours, 12 attempts);
a paused queue runs its periods oldest first once unpaused. Persist the
returned dict on the script. Batches must be idempotent per period.
