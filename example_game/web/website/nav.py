"""The primary-navigation table for this game's website.

Why the route names live here in Python rather than as ``{% url %}`` calls in
``_menu.html``: the menu is included from ``base.html``, so a name that does not
reverse is a ``NoReverseMatch`` on *every page of the site*, not just the page
with the bad link. And the names are easy to get wrong, because the nine contrib
web surfaces this game mounts use three different reverse forms for real reasons
(see ``web/website/urls.py``):

- ``app_name`` declared in the contrib, bare include -> ``evennia_maps:``,
  ``evennia_regions:``, ``evennia_calendar:``, ``evennia_plots:``
- no ``app_name``, namespace supplied at include time -> ``evennia_scenes:``,
  ``evennia_boards:``
- bare names that must *not* be namespaced -> ``lore-list``, ``job-list``,
  ``xp-summary``

So ``build_nav()`` reverses defensively and drops what does not resolve, the same
contract ``evennia_maps.overlays.overlay_url_templates()`` uses for the map's
outbound links. Unmount a contrib in ``web/website/urls.py`` and its entry
disappears from the menu; the site keeps rendering. That is the behaviour
``TestNavCoversEveryWebSurface`` pins down.

Grouping is by *kind of thing*, deliberately not by in-character vs
out-of-character. ``evennia_boards`` is the reason: ``Board.board_type`` is
``ic``/``ooc`` per board, so Boards is one surface serving both, and an IC/OOC
navbar axis would have to either split it or misfile it. "Setting / Events /
Community" sidesteps that -- and the board list renders each board's type per
row anyway, so the distinction shows up one click in.
"""

import logging

from django.urls import NoReverseMatch, reverse

logger = logging.getLogger("evennia")

# Visibility gates. An entry whose gate the request fails is omitted rather than
# rendered-and-403ing, so the anonymous menu only shows pages an anonymous
# visitor can actually read.
PUBLIC = "public"
AUTHENTICATED = "authenticated"
STAFF = "staff"

# (group label, ((item label, route name, gate), ...))
NAV_GROUPS = (
    (
        "Setting",
        (
            ("Map", "evennia_maps:plane-list", PUBLIC),
            ("Regions", "evennia_regions:region-list", PUBLIC),
            # lore-list, not lore-compendium: LoreListView is the public index of
            # PUBLISHED entries (LoreDetailView then serves body-or-stub per the
            # viewer's acquisitions). The "what my character knows" view is
            # /lore/mine/, which is account state and lives in ACCOUNT_LINKS.
            ("Lore", "lore-list", PUBLIC),
        ),
    ),
    (
        "Events",
        (
            ("Scenes", "evennia_scenes:scene-list", PUBLIC),
            ("Plots", "evennia_plots:plot-list", PUBLIC),
            ("Calendar", "evennia_calendar:calendar-list", PUBLIC),
        ),
    ),
    (
        "Community",
        (
            ("Boards", "evennia_boards:board-list", PUBLIC),
            ("Characters", "characters", PUBLIC),
            ("Channels", "channels", PUBLIC),
        ),
    ),
)

# Rendered inside the account dropdown. These are account *state* rather than
# places to browse -- all of them redirect or 403 without a login, and the first
# three additionally want a puppet.
ACCOUNT_LINKS = (
    ("My XP", "xp-summary", AUTHENTICATED),
    ("My Tickets", "job-list", AUTHENTICATED),
    ("My Lore", "lore-compendium", AUTHENTICATED),
    ("Lore Queue", "lore-queue", STAFF),
    ("All Jobs", "job-all", STAFF),
    ("Plot Arcs", "evennia_plots:plot-arc-list", STAFF),
)


def _passes_gate(request, gate):
    """True if *request* may see an entry with this visibility gate."""
    if gate == PUBLIC:
        return True
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    if gate == STAFF:
        return bool(user.is_staff)
    return True


def _resolve(name):
    """``reverse(name)``, or None if the route is not mounted.

    Not an error: a game that drops a contrib from ``web/website/urls.py`` should
    lose one menu entry, not every page. Debug-level because during development
    the log line is the only clue that a nav entry silently vanished.
    """
    try:
        return reverse(name)
    except NoReverseMatch:
        logger.debug("nav: no route named %r; omitting it from the menu", name)
        return None


def _build_entries(request, table):
    """[(label, url), ...] for the rows that both resolve and pass their gate."""
    entries = []
    for label, name, gate in table:
        if not _passes_gate(request, gate):
            continue
        url = _resolve(name)
        if url is not None:
            entries.append((label, url))
    return entries


def _active_url(request, entries):
    """The single best prefix match for ``request.path``, or None.

    Matching is on URL path prefix rather than on route name, because the three
    reverse forms above give no uniform name to match on -- and prefix matching
    is what makes a detail page light up its section (``/scenes/12/`` activates
    Scenes). Longest match wins, and the comparison runs across the *whole* menu
    at once, so ``/lore/mine/`` activates "My Lore" only rather than lighting up
    "Lore" in the Setting group as well.
    """
    path = getattr(request, "path", "") or ""
    best = None
    for _label, url in entries:
        # "/" would prefix-match every page. Home is the brand link rather than a
        # menu entry, so nothing in the tables reverses to it, but guard anyway.
        if url == "/":
            continue
        if path.startswith(url) and (best is None or len(url) > len(best)):
            best = url
    return best


def _as_items(entries, active_url):
    return [{"label": label, "url": url, "active": url == active_url} for label, url in entries]


def build_menu(request):
    """The whole menu: ``{"groups": [...], "account": {"personal", "staff"}}``.

    One entry point rather than two so the active-entry rule in ``_active_url``
    can see every candidate at once. Groups left with no items -- every route
    unmounted, or every entry gated out -- are dropped rather than rendered empty.
    """
    grouped = [(label, _build_entries(request, table)) for label, table in NAV_GROUPS]
    personal = _build_entries(request, [row for row in ACCOUNT_LINKS if row[2] == AUTHENTICATED])
    staff = _build_entries(request, [row for row in ACCOUNT_LINKS if row[2] == STAFF])

    candidates = [entry for _label, entries in grouped for entry in entries]
    candidates += personal + staff
    active_url = _active_url(request, candidates)

    groups = []
    for label, entries in grouped:
        if not entries:
            continue
        items = _as_items(entries, active_url)
        groups.append(
            {
                "label": label,
                "items": items,
                "active": any(item["active"] for item in items),
            }
        )

    return {
        "groups": groups,
        "account": {
            "personal": _as_items(personal, active_url),
            "staff": _as_items(staff, active_url),
        },
    }
