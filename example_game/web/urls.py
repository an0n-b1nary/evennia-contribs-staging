"""
This is the starting point when a user enters a url in their web browser.

The urls is matched (by regex) and mapped to a 'view' - a Python function or
callable class that in turn (usually) makes use of a 'template' (a html file
with slots that can be replaced by dynamic content) in order to render a HTML
page to show the user.

This file includes the urls in website, webclient and admin. To override you
should modify urls.py in those sub directories.

Search the Django documentation for "URL dispatcher" for more help.

"""

from django.urls import include, path

# default evennia patterns
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

# add patterns
urlpatterns = [
    # website
    path("", include("web.website.urls")),
    # webclient
    path("webclient/", include("web.webclient.urls")),
    # web admin
    path("admin/", include("web.admin.urls")),
    # Contrib REST API routers. Both are DRF DefaultRouters and are mounted
    # at the same prefix, which is what each contrib's README documents:
    # their route names (api-plane-*, api-region-*) are already distinct, and
    # the maps live map finds its tile feed by reversing "api-plane-tiles"
    # (MAPS_TILES_URL_NAME), so mounting either under a namespace would break
    # that lookup. The one shared name is DRF's own "api-root" — the
    # browsable index at /api/v1/ therefore lists only the first router's
    # entry point; /api/v1/regions/ is reachable regardless.
    path("api/v1/", include("evennia_maps.api.urls")),
    path("api/v1/", include("evennia_regions.api.urls")),
    # add any extra urls here:
    # path("mypath/", include("path.to.my.urls.file")),
]

# 'urlpatterns' must be named such for Django to find it.
urlpatterns = urlpatterns + evennia_default_urlpatterns
