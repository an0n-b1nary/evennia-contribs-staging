"""
This reroutes from an URL to a python view-function/class.

The main web/urls.py includes these routes for all urls (the root of the url)
so it can reroute to all website pages.

Contrib website surfaces are mounted here. **Four of the twelve contribs are
mounted, not all of them** — the map is the reason for each one:

- `evennia_maps` and `evennia_regions` are the surfaces this sandbox exists
  to demonstrate.
- `evennia_scenes` and `evennia_calendar` are mounted because the map *links
  out* to them. `evennia_maps.overlays.overlay_url_templates()` reverses
  `evennia_scenes:scene-detail` and `evennia_calendar:calendar-event-detail`
  (see MAPS_OVERLAY_URL_NAMES) and silently drops any that do not resolve, so
  without these two includes the tile popups would render their recent-log
  and upcoming-event entries as plain text. Not mounting them would hide a
  whole overlay feature behind a no-op.

The remaining web surfaces (boards, lore, plots, jobs, xp) stay unmounted for
now; they are each their own hand-check and belong to their own wiring pass.

Namespacing: `evennia_maps`, `evennia_regions` and `evennia_calendar` declare
`app_name` in their own urls.py, so a bare include() namespaces them.
`evennia_scenes` does not, so it is included with an explicit
(module, namespace) 2-tuple — its README documents that form. The maps
templates reverse their own routes through the `evennia_maps` namespace, so
mounting it un-namespaced would 500 the map page rather than fail quietly.

`evennia_scenes` is mounted at "" because its own urlpatterns already carry
the "scenes/" prefix on every route.
"""

from django.urls import include, path
from evennia.web.website.urls import urlpatterns as evennia_website_urlpatterns

# add patterns here
urlpatterns = [
    path("map/", include("evennia_maps.urls")),
    path("regions/", include("evennia_regions.urls")),
    path("calendar/", include("evennia_calendar.urls")),
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
]

# read by Django
urlpatterns = urlpatterns + evennia_website_urlpatterns
