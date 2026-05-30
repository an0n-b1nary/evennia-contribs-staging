# evennia-links

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

Abstract base models and helpers for cross-system bridge ("link") models in
[Evennia](https://www.evennia.com/) games.

This package is the **shared hub** that domain contribs depend on. It ships
no tables of its own — only abstract Django models and a small registration
helper. The concrete bridge models that connect your game's domain apps
together live in your own game code (or in downstream domain contribs like
`evennia-scenes`, `evennia-plots`, etc.).

---

## What's included

| Name | Module | Purpose |
|---|---|---|
| `AbstractLink` | `links.py` | Minimal base: `created_at` + `create_link()` |
| `AbstractAuthoredLink` | `links.py` | Adds `created_by` / `created_by_name` audit block |
| `AbstractVersion` | `versioning.py` | Append-only version history for any text field |
| `AbstractArchived` + `ArchivedManager` | `archiving.py` | Soft-archive with default-manager filtering |
| `connect_on_ready` | `listeners.py` | Import-order-safe signal-registration helper |

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

No migrations to run — this contrib ships only abstract models.

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
