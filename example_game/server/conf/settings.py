r"""
Evennia settings file.

The available options are found in the default settings file found
here:

https://www.evennia.com/docs/latest/Setup/Settings-Default.html

Remember:

Don't copy more from the default file than you actually intend to
change; this will make sure that you don't overload upstream updates
unnecessarily.

When changing a setting requiring a file system path (like
path/to/actual/file.py), use GAME_DIR and EVENNIA_DIR to reference
your game folder and the Evennia library folders respectively. Python
paths (path.to.module) should be given relative to the game's root
folder (typeclasses.foo) whereas paths within the Evennia library
needs to be given explicitly (evennia.foo).

If you want to share your game dir, including its settings, you can
put secret game- or server-specific settings in secret_settings.py.

"""

# Use the defaults from Evennia unless explicitly overridden
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "Contrib Sandbox"

# Use the stock Django admin site instead of Evennia's customized one. Evennia's
# admin only surfaces its own registered models; with the base site, the
# contribs' custom models (boards, plots, lore, calendar, jobs, etc.) appear too.
# Tradeoff: Evennia's own account/object/script admin pages aren't registered on
# the default site, so they won't show here.
EVENNIA_ADMIN = False

######################################################################
# Contrib apps
######################################################################

# evennia_links must precede every contrib that depends on it (its abstract
# base models are imported at their app-load time).
INSTALLED_APPS += [
    "evennia_links",
    "evennia_economy",
    "evennia_rp_resources",
    "evennia_rptracker",
    "evennia_scenes",
    "evennia_boards",
    "evennia_lore",
    "evennia_plots",
    "evennia_calendar",
    # Regions/maps sit after the three overlay partners above (scenes, lore,
    # calendar) purely for readability: each of those connects a tile-overlay
    # provider from its own ready(), gated on evennia_maps being installed,
    # and listing them in that order makes the gates read top-down. Django
    # populates the whole app registry before any ready() runs, so
    # apps.is_installed() in those gates does not actually depend on order.
    "evennia_regions",
    "evennia_maps",
    "evennia_jobs",
    "evennia_xp",
    "evennia_accessibility",
    "evennia_posing",
    "evennia_social",
    # RP kernel first; both character builds and contests depend on it.
    "evennia_rp_rules",
    "evennia_rp_chargen",
    # Equipment requires chargen (worn gear's requirements and the change guard),
    # so it is absent whenever chargen is.
    "evennia_rp_equipment",
    "evennia_rp_contest",
    # This game's own glue module + seed_sandbox management command, plus
    # (via its apps.py) the pose_recorded signal connect. No models —
    # registered only so Django's management-command autodiscovery finds
    # world/sandbox/management/commands/, and so apps.py's AppConfig is
    # discovered and its ready() runs.
    "world.sandbox",
]

######################################################################
# Economy (evennia-economy) — integer purses, passive income and atomic trades
######################################################################
RP_ECONOMY_REVEALED = True
RP_ECONOMY_FROZEN = False
RP_ECONOMY_CURRENCY = ("coin", "coins")
RP_ECONOMY_WEEKLY_AMOUNT = 100
RP_ECONOMY_BASE_CAP_WEEKS = 5
RP_ECONOMY_TAPER_FRACTION = 0.8
RP_ECONOMY_STARTING_STIPEND = 100
RP_ECONOMY_REVEAL_STIPEND = 100
RP_ECONOMY_PERIOD_SECONDS = 604800
RP_ECONOMY_OFFER_TIMEOUT = 600
RP_ECONOMY_MAX_OPEN_OFFERS = 5
RP_ECONOMY_MAX_STALLS = 1
RP_ECONOMY_STALL_SLOTS = 8
RP_ECONOMY_STALL_CAP_RAISE = 100
RP_ECONOMY_QUIET_STALL_WEEKS = 5
RP_ECONOMY_STAFF_LOCK = "cmd:perm(Builder)"
RP_ECONOMY_FLAG_REVIEW_HOOK = "evennia_jobs.integrations.staff_review.file_review_job"

######################################################################
# RP resources (evennia-rp-resources) — passive accrual and gathering choices
######################################################################
RP_RESOURCES_REVEALED = True
RP_RESOURCES_CATALOG = "world.sandbox.resources.catalog"
RP_RESOURCES_CATEGORIES = [
    ("materials", "Materials"),
    ("provisions", "Provisions"),
    ("essences", "Essences"),
]
RP_RESOURCES_WEEKLY_QUANTITY = 6
RP_RESOURCES_BASE_CAP = 30
RP_RESOURCES_TAPER_FRACTION = 0.8
RP_RESOURCES_PERIOD_SECONDS = 604800
RP_RESOURCES_LEAN_MULTIPLIER = 2
RP_RESOURCES_STAFF_LOCK = "cmd:perm(Builder)"
RP_ECONOMY_ELIGIBLE = None  # Every playable character; no RP/session requirement.
SOCIAL_PROFILE_PROVIDERS = ["evennia_rp_resources.profile.gathering_field"]

######################################################################
# RP rules (evennia-rp-rules) — game values and optional sheet/stat-block seams
######################################################################

RP_RULES_RULESET = "world.ruleset"
RP_RULES_SUBJECT_ADAPTER = "world.sandbox.glue.rp_subject_adapter"
RP_RULES_VOCABULARY = "world.sandbox.glue.rp_vocabulary"
RP_RULES_MODIFIER_PROVIDERS = []

######################################################################
# RP character builds (evennia-rp-chargen) — no typeclass mixin required
######################################################################

from world import ruleset as rp_values

RP_CHARGEN_STAFF_LOCK = "cmd:perm(Builder)"
RP_CHARGEN_ALLOCATION = {
    "path": "evennia_rp_chargen.allocation.PointBuyAllocation",
    "params": rp_values.POINT_BUY,
}
RP_CHARGEN_PIP_BUDGET = rp_values.PIPS["budget"]
RP_CHARGEN_PIP_CAP = rp_values.PIPS["cap"]
RP_CHARGEN_WEAKNESS_CAP = rp_values.PIPS["weakness_cap"]
RP_CHARGEN_LOADOUT_BUDGET = rp_values.LOADOUT_BUDGET
# Player-facing nouns, shown at the contrib defaults so they're easy to find:
# change any word here. Stat, tag and ability names live in world/ruleset.py.
RP_CHARGEN_ALLOCATION_NOUN = "build points"
RP_CHARGEN_PIP_NOUN = "pips"
RP_CHARGEN_WEAKNESS_NOUN = "weakness"
RP_CHARGEN_LOADOUT_NOUN = "loadout"
RP_CHARGEN_LOADOUT_UNIT = "points"
RP_CHARGEN_ALLOWANCE_NOUN = "starting allowance"
RP_CHARGEN_LOCK_SCOPES = ("pips", "loadout")
RP_CHARGEN_LOCK_TTL = 3 * 60 * 60
RP_CHARGEN_REQUIRE_APPROVAL = False
RP_CHARGEN_RPTRACKER_APP_LABEL = "evennia_rptracker"
RP_CHARGEN_CATALOG_SEED = "world.ruleset.CATALOG"
RP_CHARGEN_STARTING_ALLOWANCE = rp_values.STARTING_ALLOWANCE
RP_CHARGEN_UPGRADE_COST = rp_values.UPGRADE_COST
# Purchases use the starting allowance first, then earned XP when installed.
RP_CHARGEN_XP_LEDGER = "evennia_rp_chargen.integrations.xp.EvenniaXPLedger"

######################################################################
# RP equipment (evennia-rp-equipment) — display hooks in typeclasses/characters.py
######################################################################

# Plain gear anyone can make; requirements commit a build and grant nothing.
RP_EQUIPMENT_TYPECLASS = "evennia_rp_equipment.typeclasses.Equipment"
RP_EQUIPMENT_SLOTS = ("head", "body", "hands", "feet", "weapon", "accessory")
RP_EQUIPMENT_ITEM_CAP = 20
RP_EQUIPMENT_STAFF_LOCK = "cmd:perm(Builder)"

######################################################################
# RP contests (evennia-rp-contest) — informal storytellers and chosen approaches
######################################################################

RP_CONTEST_STAFF_LOCK = "cmd:perm(Builder)"
RP_CONTEST_CAN_SET_CHALLENGE = "cmd:all()"
RP_CONTEST_DEFAULT_DIFFICULTY = rp_values.DEFAULT_DIFFICULTY
# Tag kinds `+test` accepts: domains, and the fighting styles in world/ruleset.py.
RP_CONTEST_TAG_KIND = ["domain", "style"]
RP_CONTEST_SHOW_RATINGS_TO_ROOM = False
RP_CONTEST_CHALLENGE_IDLE_TTL = 3 * 60 * 60
RP_CONTEST_SCENES_APP_LABEL = "evennia_scenes"
RP_CONTEST_RPTRACKER_APP_LABEL = "evennia_rptracker"

######################################################################
# Accessibility (evennia-accessibility)
######################################################################

OPTIONS_ACCOUNT_DEFAULT["screenreader_mode"] = (
    "Render plain-text output suited for screen readers.",
    "Boolean",
    False,
)

######################################################################
# Posing (evennia-posing) — account options the contrib expects the game
# to register (see its README §"Register the account options"). Without
# these, +poseheader/+highlight raise "Option not found!".
######################################################################

OPTIONS_ACCOUNT_DEFAULT["show_pose_headers"] = (
    "Show character name headers above poses.",
    "Boolean",
    True,
)
OPTIONS_ACCOUNT_DEFAULT["pose_header_format"] = (
    "Format string for pose headers ({name} placeholder required).",
    "Text",
    "--- {name} ---",
)
OPTIONS_ACCOUNT_DEFAULT["pose_separator"] = (
    "Visual separator between poses.",
    # Text.deserialize rejects empty strings and logs a traceback on every
    # pose. BaseOption keeps normal text input validation and permits blank.
    "BaseOption",
    "",
)
OPTIONS_ACCOUNT_DEFAULT["highlight_enabled"] = (
    "Highlight character names in poses and room descriptions.",
    "Boolean",
    True,
)
OPTIONS_ACCOUNT_DEFAULT["highlight_self_color"] = (
    "Color for your own name in poses.",
    "Color",
    "w",
)
OPTIONS_ACCOUNT_DEFAULT["highlight_others_color"] = (
    "Color for other character names.",
    "Color",
    "c",
)

######################################################################
# Spawn points - where a new character starts, and falls back to
######################################################################

# Both must stay *dbrefs*. Evennia resolves them with
# ObjectDB.objects.get_id() (evennia/accounts/accounts.py:962), which accepts a
# dbref and nothing else - a room name here yields no location at all and
# strands the new character. That rules out pointing them at a room the seeder
# creates, whose dbref changes on every rebuild.
#
# #2 is Limbo: created once by `evennia migrate` and never deleted, it is the
# one dbref that survives both a reseed and a golden-DB restore. So rather than
# chase a moving dbref, `evennia seed_sandbox` re-dresses #2 *into* the Sandbox
# Plaza instead of creating the Plaza fresh (see seed_sandbox.py::_origin_room).
# These two match Evennia's own defaults and are spelled out only because the
# seeder now depends on them.
START_LOCATION = "#2"
DEFAULT_HOME = "#2"

######################################################################
# Social (evennia-social) — see its README §"Register the settings this
# contrib reads".
######################################################################

# The OOC hub, which is the Arrival Hall - the room new characters spawn into
# and the middle of the OOC wing's hub-and-spoke. Required for +ooc and +home's
# fallback. Despite the setting's name, evennia_social resolves it with
# search_object() (evennia_social/commands/navigation.py:_resolve_ooc_room),
# which matches a room *name* as happily as a dbref.
#
# Pointing +ooc at the room a player is already standing in would make the
# command demo as a no-op, so the wing puts the commands it teaches out on the
# spokes and keeps the hub as the place they all return to.
#
# Kept as a name, not "#2", even though the Arrival Hall *is* #2: the name is
# what world/sandbox/content.py owns, and a future world could move the hub
# without touching this file.
#
# Read from content.py rather than restated, because restating it made this
# the one place a rename could silently break: every other reference to a room
# name in this game is derived from that file, and a stale literal here would
# leave +ooc searching for a room that no longer exists. Importing it at
# settings time is safe - content.py imports nothing but dataclasses, and both
# package __init__ files are empty - and it is the only settings value that
# needs it. START_LOCATION and DEFAULT_HOME below cannot be derived the same
# way: Evennia resolves those with ObjectDB.objects.get_id(), which takes a
# dbref and not a name.
from world.sandbox import content as _sandbox_content

OOC_ROOM_DBREF = _sandbox_content.OOC_ROOMS_BY_SLUG[_sandbox_content.ARRIVAL_SLUG].name

# "visited" restricts player @tel to rooms they've visited or control;
# "open" allows any public room.
TELEPORT_MODE = "visited"

######################################################################
# Networking — shifted port block
######################################################################

# This droplet already runs a separate, unrelated Evennia game on the
# default ports (4000-4006). Every port below is shifted by +100 so the two
# games never collide. AMP_PORT is the easy one to forget — it's "internal"
# but still binds a real TCP port on the same host.
TELNET_PORTS = [4100]
WEBSERVER_PORTS = [(4101, 4105)]
WEBSOCKET_CLIENT_PORT = 4102
AMP_PORT = 4106
# SSL/SSH stay disabled (SSL_ENABLED / SSH_ENABLED default to False upstream).

######################################################################
# Public exposure (subdomain + TLS via the droplet's existing nginx)
######################################################################

# Replace with the real subdomain when deploying — keep this file's
# committed value as a placeholder so the repo never names the droplet's
# actual domain (anonymity guard).
SANDBOX_HOSTNAME = "sandbox.YOURDOMAIN"

# localhost/127.0.0.1 are included so the local dry-run (README) and nginx
# (which proxies with Host: <hostname>, but health-checks may use localhost)
# both pass Django's Host header check. Harmless in production — those hosts
# are only reachable on-box anyway.
ALLOWED_HOSTS = [SANDBOX_HOSTNAME, "localhost", "127.0.0.1"]
# nginx (the reverse proxy) talks to the Server from localhost.
UPSTREAM_IPS = ["127.0.0.1"]
SERVER_HOSTNAME = SANDBOX_HOSTNAME
WEBSOCKET_CLIENT_URL = f"wss://{SANDBOX_HOSTNAME}/ws"
# Django 4+ checks the Origin header on secure POSTs (e.g. the web-admin login
# form); the browser sends an https origin but nginx proxies to the Server over
# plain HTTP, so the https origin must be trusted explicitly. Override this in
# secret_settings.py alongside SANDBOX_HOSTNAME (see README step 4).
CSRF_TRUSTED_ORIGINS = [f"https://{SANDBOX_HOSTNAME}"]

# Bind the HTTP webserver-proxy and the websocket to localhost only. nginx
# (on this same host) reverse-proxies both, and the only public entry points
# are TLS via the subdomain (HTTP/WS) and telnet on 4100. This keeps plaintext
# HTTP/WS off every public interface — defense-in-depth alongside the firewall,
# which opens only telnet. Telnet stays on all interfaces (its default) so MUD
# clients can reach it directly.
WEBSERVER_INTERFACES = ["127.0.0.1"]
WEBSOCKET_CLIENT_INTERFACE = "127.0.0.1"
# Used by evennia-accessibility's absolute_web_url() and the scenes/plots/
# calendar |lu MXP link builders so telnet clients get real URLs.
SITE_URL = f"https://{SANDBOX_HOSTNAME}"

# nginx terminates TLS and proxies to the Server over plain HTTP; this header
# (nginx sends `X-Forwarded-Proto: $scheme`) tells Django the original request
# was HTTPS, so scheme detection, secure cookies, and the CSRF origin check all
# work. Generic (no domain), so it lives here, not in secret_settings.py.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# This is a real, persistent, publicly-reachable server — never weaken the
# password hasher here. A fast MD5 hasher belongs only in a test-suite
# settings module, never in a production-shaped one like this.

######################################################################
# XP integration — collectors/sweeps/hooks shipped by the contribs
# themselves (not game-local glue). See world/sandbox/glue.py for the
# two RP-rules hooks that stay game-local.
######################################################################

XP_STAFF_LOCK = "cmd:perm(Builder)"

XP_MULTIPLIER_RESOLVER = "evennia_plots.integrations.gating.resolve_xp_multiplier"

XP_COLLECTORS = [
    ("rp_session", "evennia_rptracker.integrations.xp.collect_rp_sessions"),
    ("rp_channel_session", "evennia_rptracker.integrations.xp.collect_rp_channel_sessions"),
    ("lore_authored", "evennia_lore.integrations.xp.collect_lore_authored"),
    ("lore_inspiration", "evennia_lore.integrations.xp.collect_lore_inspiration"),
    ("cutscene", "evennia_boards.integrations.xp.collect_cutscene_posts"),
    ("thread_bonus", "evennia_plots.integrations.xp.collect_thread_bonuses"),
    ("arc_bonus", "evennia_plots.integrations.xp.collect_arc_bonuses"),
]

XP_ANTIGAMING_SWEEPS = [
    "evennia_rptracker.antigaming.sweep_rp_sessions",
    "evennia_boards.integrations.xp.sweep_cutscene_spam",
    "evennia_plots.integrations.antigaming.sweep",
]

# Only rptracker ships a post-batch hook. evennia_plots has no flip_thread_flags
# equivalent — its collectors write idempotent PlotBonusCredit rows instead, so
# there is nothing to flip after the batch writes XPLog rows.
XP_POST_BATCH_HOOKS = [
    "evennia_rptracker.integrations.xp.flip_session_flags",
    "evennia_rptracker.integrations.xp.flip_channel_session_flags",
]

# Removing a partner also removes its scheduled XP imports. The remaining
# collectors keep running rather than aborting the whole weekly batch.
XP_COLLECTORS = [item for item in XP_COLLECTORS if item[1].split(".", 1)[0] in INSTALLED_APPS]
XP_ANTIGAMING_SWEEPS = [
    hook for hook in XP_ANTIGAMING_SWEEPS if hook.split(".", 1)[0] in INSTALLED_APPS
]
XP_POST_BATCH_HOOKS = [
    hook for hook in XP_POST_BATCH_HOOKS if hook.split(".", 1)[0] in INSTALLED_APPS
]

######################################################################
# RPTracker configuration
######################################################################

RPTRACKER_STAFF_LOCK = "cmd:perm(Builder)"
RPTRACKER_SESSION_IDLE_TIMEOUT = 3600
RPTRACKER_PARTNER_ACTIVE_WINDOW = 3600
RPTRACKER_SESSION_ACTIVATION_POSES = 2
RPTRACKER_POSE_FLUSH_THRESHOLD = 5
RPTRACKER_IDLE_CHECK_INTERVAL = 300
RPTRACKER_MANUAL_END_ABUSE_COUNT = 3
RPTRACKER_POSE_SPAM_MIN_COUNT = 20
RPTRACKER_POSE_SPAM_MAX_SECONDS = 600
RPTRACKER_CHANNEL_SESSION_IDLE_TIMEOUT = 1800
RPTRACKER_CHANNEL_PARTNER_ACTIVE_WINDOW = 1800
RPTRACKER_CHANNEL_ACTIVATION_MESSAGES = 2
RPTRACKER_CHANNEL_ELIGIBLE = None
RPTRACKER_REGIONS_APP_LABEL = "evennia_regions"

# NOTE: RPTRACKER_SCENES_APP_LABEL is intentionally left unset. Its code
# default is "evennia_scenes" (contribs/game_systems/evennia_rptracker/apps.py),
# which already matches this game's evennia_scenes app label — no override
# needed. (The contrib's own README §"Scene bridge" claims the bridge's FK is
# "hardcoded to scenes.Scene"; that line is stale — RPSessionSceneLink.scene_id
# is a plain PositiveBigIntegerField soft-ref resolved dynamically via
# apps.get_model(label, "Scene"), so the code default is correct as-is.)

RPTRACKER_SCENE_DISPLAY = (
    "evennia_scenes.display.render_scene_ref" if "evennia_scenes" in INSTALLED_APPS else None
)
# Both hooks ship in the partner contrib; each is gated so removing the partner
# leaves the hook unset instead of pointing at a module that can't import.
RPTRACKER_XP_PROJECTION = (
    "evennia_xp.projection.activity_lines" if "evennia_xp" in INSTALLED_APPS else None
)
RPTRACKER_FLAG_REVIEW_HOOK = (
    "evennia_jobs.integrations.staff_review.file_review_job"
    if "evennia_jobs" in INSTALLED_APPS
    else None
)

######################################################################
# Scenes configuration
######################################################################

SCENES_STAFF_LOCK = "cmd:perm(Builder)"

######################################################################
# Boards configuration
######################################################################

BOARDS_STAFF_LOCK = "cmd:perm(Builder)"
BOARDS_CALENDAR_APP_LABEL = "evennia_calendar"
BOARDS_ANTIGAMING_REPORTER = (
    "evennia_jobs.integrations.staff_review.file_review_job"
    if "evennia_jobs" in INSTALLED_APPS
    else None
)

######################################################################
# Calendar configuration
######################################################################

CALENDAR_STAFF_LOCK = "cmd:perm(Builder)"

######################################################################
# Jobs configuration
######################################################################

JOBS_STAFF_LOCK = "cmd:perm(Builder)"

######################################################################
# Lore configuration
######################################################################

LORE_STAFF_LOCK = "cmd:perm(Builder)"
LORE_REQUIRE_APPROVAL = False
LORE_PASSIVE_WEEKLY_CEILING = 5

from decimal import Decimal

LORE_PASSIVE_LEAN_MULTIPLIER = Decimal("2.0")

LORE_RPTRACKER_APP_LABEL = "evennia_rptracker"
LORE_SCENES_APP_LABEL = "evennia_scenes"
LORE_PLOTS_APP_LABEL = "evennia_plots"
# Regions is installed now, so this edge is live: lore's region weighting in
# the passive trickle, its soft-ref cleanup on region deletion, and its
# has_lore map overlay all resolve RegionMembership through this label.
LORE_REGIONS_APP_LABEL = "evennia_regions"

# Shipped provider: room, primary region and plot threads, each through the
# label settings above (an absent partner just drops its part).
LORE_SESSION_CONTEXT_PROVIDER = "evennia_lore.integrations.session_context.get_session_context"

######################################################################
# Regions configuration
######################################################################

REGIONS_STAFF_LOCK = "cmd:perm(Builder)"

# REGIONS_MAPS_APP_LABEL is left unset: its code default ("evennia_maps")
# already matches this game's maps app label, so the primary_region tile
# overlay connects itself with no configuration at all.

######################################################################
# Maps configuration
######################################################################

MAPS_STAFF_LOCK = "cmd:perm(Builder)"

# Ordered: the first tag present on a room's terrain_tags wins as the tile's
# denormalized terrain. A room whose tags are all absent from this list
# resolves to no terrain at all, which is a different state from having a
# terrain with no sprite - see the tileset below.
#
# "water" leads so that the seeded Harbor Steps, which carries both "water"
# and "urban", resolves to one deterministic answer. That precedence exists to
# be exercised, not just declared.
MAPS_TERRAIN_PRECEDENCE = ["water", "forest", "hills", "scrub", "urban"]

# {terrain key: sprite URL} for the web map. The four sprites are 32x32 flat
# colour swatches in web/static/sandbox/terrain/ - placeholders standing in
# for real tile art, and safe to replace with anything of the same size.
#
# "scrub" is deliberately absent even though it is a perfectly valid terrain
# above. A terrain with no sprite renders as the map's plain fallback swatch,
# and the seeded Causeway carries it so that fallback appears on the grid
# beside real sprites rather than only in the contrib's test suite. Deleting
# this setting entirely is also a supported state: the map then draws every
# tile as a fallback swatch.
MAPS_TERRAIN_TILESET = {
    "water": "/static/sandbox/terrain/water.png",
    "forest": "/static/sandbox/terrain/forest.png",
    "hills": "/static/sandbox/terrain/hills.png",
    "urban": "/static/sandbox/terrain/urban.png",
}

# Labels and colours for the same terrains (evennia_maps 0.6). The tileset
# above still supplies the four sprites; "scrub" gets a colour and no sprite,
# so the Causeway shows a swatch tinted to its terrain, not the bare grey a
# terrain-less room keeps. Together they put every terrain-display path on
# the seeded grid: sprite, tinted swatch, and no terrain at all.
MAPS_TERRAINS = {
    "water": {"label": "Open water", "color": "#2f6e9e"},
    "forest": {"label": "Woodland", "color": "#2e5d34"},
    "hills": {"label": "Hills", "color": "#7a6a4a"},
    "scrub": {"label": "Dry scrub", "color": "#8a7a4a"},
    "urban": {"label": "Town", "color": "#6b6b78"},
}

# The OOC wing is not part of the physical world, so its rooms must never
# take a cell on the grid. Without this, `@dig north=<somewhere OOC>` from a
# mapped room would annex one silently - the tile is a side effect of digging
# an exit, not something anyone asked for, which is exactly why the contrib
# enforces this on the listener and leaves an explicit +map/place alone.
# `+map/check` reports any tile that ends up on one of these anyway.
MAPS_UNMAPPABLE_ROOM_TYPES = ("ooc",)

# Deliberately absent: every overlay setting. The six overlay layers
# (primary_region, has_active_scene, recent_scene_count, recent_scenes,
# has_lore, upcoming_events) light up purely from which partner contribs are
# in INSTALLED_APPS — that is the whole point of the collect_tile_overlays
# signal design, and configuring it here would defeat it. MAPS_OVERLAY_URL_NAMES
# is likewise left at its defaults, which already name the routes this game
# mounts in web/website/urls.py.

######################################################################
# Plots configuration
######################################################################

PLOTS_STAFF_LOCK = "cmd:perm(Builder)"
PLOTS_SCENES_APP_LABEL = "evennia_scenes"
PLOTS_CALENDAR_APP_LABEL = "evennia_calendar"
PLOTS_BOARDS_APP_LABEL = "evennia_boards"

######################################################################
# REST API
######################################################################

# Evennia's settings_default already ships both
# "rest_framework" and "django_filters" in INSTALLED_APPS and a REST_FRAMEWORK
# block, and the contrib viewsets declare their own authentication,
# permission, pagination and filter classes rather than relying on the
# project-wide defaults. The contrib routers are mounted in web/urls.py;
# REST_API_ENABLED stays False: that flag gates *Evennia's own* /api/
# routes (objects, accounts, scripts), which this sandbox does not expose.
# The contrib routers are separate; web/templates/rest_framework/api.html
# guards optional schema/documentation links on their browsable pages. Games
# mounting these routers need both the URL includes and this template override
# when Evennia's own API is disabled; see the maps and regions install guides.

######################################################################
# Website navigation
######################################################################

# Shared by native-page categories, the staff menu, and staff-only page links.
# Keep this as the single HTTP staff policy. Set EVENNIA_WEB_STAFF_PREDICATE to
# a dotted callable(request) when the game needs a custom rule; it is
# authoritative and fails closed if it cannot be loaded or raises. The
# contrib *_STAFF_LOCK settings below remain for in-game commands and
# authoring, not for HTTP staff chrome.
EVENNIA_WEB_STAFF_LOCK = "cmd:perm(Builder)"

# base.html includes _menu.html on every render, including on pages rendered by
# contrib views this game does not own. A context processor is the only seam
# that reaches all of them; see web/website/context_processors.py for why this
# is not a template tag.
#
# Appended rather than reassigned: Evennia's settings_default builds the whole
# TEMPLATES list (including sekizai and Evennia's own general_context), and
# restating it here would silently freeze this game against upstream changes to
# that list.
TEMPLATES[0]["OPTIONS"]["context_processors"] += [
    "web.website.context_processors.site_menu",
]

######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
