"""Template context this game adds to every page.

``base.html`` includes ``_menu.html`` on every render, so the menu data has to be
present in every template context -- including the ones rendered by contrib views
this game does not own and cannot add ``get_context_data`` to. A context
processor is the seam for that, and it is how Evennia supplies its own
``game_name``/``webclient_enabled``/``account`` (see
``evennia.web.utils.general_context``).

A context processor rather than an inclusion template tag because ``web.website``
is not in ``INSTALLED_APPS`` -- Django only autodiscovers ``templatetags/``
packages inside installed apps, so a tag defined here would never be found. A
context processor is just a dotted path in ``TEMPLATES`` and needs no app.

Registered in ``server/conf/settings.py``.
"""

from web.website.nav import build_menu


def site_menu(request):
    """``nav_groups`` and ``nav_account`` for ``_menu.html``.

    Cost is one ``reverse()`` per menu entry per render (~15). ``reverse()`` goes
    through Django's cached URL resolver, so these are dictionary lookups rather
    than pattern matching.
    """
    menu = build_menu(request)
    return {"nav_groups": menu["groups"], "nav_account": menu["account"]}
