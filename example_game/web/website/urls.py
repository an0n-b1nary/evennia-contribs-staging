"""
This reroutes from an URL to a python view-function/class.

The main web/urls.py includes these routes for all urls (the root of the url)
so it can reroute to all website pages.

**Every contrib web surface this game ships is mounted here.** A playtester
reaching the site should find the same nine systems the telnet side offers, so
the two halves of the demo agree with each other.

Namespacing is not a style choice here - each contrib has one correct form, and
the wrong one breaks its pages rather than failing quietly:

- `evennia_maps`, `evennia_regions`, `evennia_calendar` and `evennia_plots`
  declare `app_name` in their own urls.py and reverse their routes through that
  namespace (`{% url 'evennia_maps:...' %}`), so a bare `include()` is right:
  Django picks the namespace up from `app_name`. Mounting them un-namespaced
  would 500 the pages that reverse their own routes.
- `evennia_scenes` and `evennia_boards` reverse through a namespace too, but
  declare no `app_name`, so the namespace has to be supplied here as an
  explicit `(module, namespace)` 2-tuple. Both READMEs document that form.
- `evennia_lore`, `evennia_jobs` and `evennia_xp` reverse their routes
  **bare** (`{% url 'lore-list' %}`), so they must be included *without* a
  namespace. Wrapping them in one would make every link in their templates a
  NoReverseMatch. This is the case that looks like an inconsistency worth
  tidying up and is not.

Prefixes: `evennia_scenes` and `evennia_boards` are mounted at "" because their
own urlpatterns already carry the "scenes/" and "boards/" prefixes on every
route. The rest carry none and take their prefix here.

Why the four map-adjacent ones matter to each other: `evennia_maps` links *out*
to scenes and calendar. `overlays.overlay_url_templates()` reverses
`evennia_scenes:scene-detail` and `evennia_calendar:calendar-event-detail` (see
MAPS_OVERLAY_URL_NAMES) and silently drops any that do not resolve, so
unmounting either would turn the tile popups' recent-log and upcoming-event
entries into plain text - a whole overlay feature hidden behind a no-op rather
than an error.
"""

from django.urls import include, path
from evennia.web.website.urls import urlpatterns as evennia_website_urlpatterns

from web.website.views.index import SandboxIndexView

# add patterns here
urlpatterns = [
    # Shadows Evennia's own `index`, which is appended below - Django takes the
    # first match, so this has to come before that append rather than after.
    # Same route name, so every {% url 'index' %} in Evennia's templates follows
    # it without change.
    path("", SandboxIndexView.as_view(), name="index"),
    path("map/", include("evennia_maps.urls")),
    path("regions/", include("evennia_regions.urls")),
    path("calendar/", include("evennia_calendar.urls")),
    path("plots/", include("evennia_plots.urls")),
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    path("", include(("evennia_boards.urls", "evennia_boards"))),
    path("lore/", include("evennia_lore.urls")),
    path("jobs/", include("evennia_jobs.urls")),
    path("xp/", include("evennia_xp.urls")),
]

# read by Django
urlpatterns = urlpatterns + evennia_website_urlpatterns
