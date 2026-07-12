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

######################################################################
# Contrib apps
######################################################################

# evennia_links must precede every contrib that depends on it (its abstract
# base models are imported at their app-load time).
INSTALLED_APPS += [
    "evennia_links",
    "evennia_rptracker",
    "evennia_scenes",
    "evennia_boards",
    "evennia_lore",
    "evennia_plots",
    "evennia_calendar",
    "evennia_jobs",
    "evennia_xp",
    "evennia_accessibility",
    # This game's own glue module + seed_sandbox management command. No
    # models — registered only so Django's management-command autodiscovery
    # finds world/sandbox/management/commands/.
    "world.sandbox",
]

######################################################################
# Accessibility (evennia-accessibility)
######################################################################

OPTIONS_ACCOUNT_DEFAULT["screenreader_mode"] = (
    "Render plain-text output suited for screen readers.",
    "Boolean",
    False,
)

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

# This is a real, persistent, publicly-reachable server — never weaken the
# password hasher here. A fast MD5 hasher belongs only in a test-suite
# settings module, never in a production-shaped one like this.

######################################################################
# XP integration — collectors/sweeps/hooks shipped by the contribs
# themselves (not game-local glue). See world/sandbox/glue.py for the
# handful of dotted-path hooks that have no shipped default.
######################################################################

XP_STAFF_LOCK = "cmd:perm(Builder)"

XP_MULTIPLIER_RESOLVER = "evennia_plots.integrations.gating.resolve_xp_multiplier"

XP_COLLECTORS = [
    ("rp_session", "evennia_rptracker.integrations.xp.collect_rp_sessions"),
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

# NOTE: RPTRACKER_SCENES_APP_LABEL is intentionally left unset. Its code
# default is "evennia_scenes" (contribs/game_systems/evennia_rptracker/apps.py),
# which already matches this game's evennia_scenes app label — no override
# needed. (The contrib's own README §"Scene bridge" claims the bridge's FK is
# "hardcoded to scenes.Scene"; that line is stale — RPSessionSceneLink.scene_id
# is a plain PositiveBigIntegerField soft-ref resolved dynamically via
# apps.get_model(label, "Scene"), so the code default is correct as-is.)

RPTRACKER_SCENE_DISPLAY = "evennia_scenes.display.render_scene_ref"
RPTRACKER_XP_PROJECTION = None  # no shipped default; cosmetic-only, omitted
RPTRACKER_FLAG_REVIEW_HOOK = "world.sandbox.glue.rptracker_flag_review_hook"

######################################################################
# Scenes configuration
######################################################################

SCENES_STAFF_LOCK = "cmd:perm(Builder)"

######################################################################
# Boards configuration
######################################################################

BOARDS_STAFF_LOCK = "cmd:perm(Builder)"
BOARDS_CALENDAR_APP_LABEL = "evennia_calendar"
BOARDS_ANTIGAMING_REPORTER = "world.sandbox.glue.boards_antigaming_reporter"

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
# evennia_regions does not exist in this repo yet (Maps/Regions haven't been
# extracted). Left at the code default ("evennia_regions") — since that app
# is never installed, region weighting simply stays inert (weight-0 signal),
# which is harmless per the contrib's soft-partner matrix.

LORE_SESSION_CONTEXT_PROVIDER = "world.sandbox.glue.lore_session_context_provider"

######################################################################
# Plots configuration
######################################################################

PLOTS_STAFF_LOCK = "cmd:perm(Builder)"
PLOTS_SCENES_APP_LABEL = "evennia_scenes"
PLOTS_CALENDAR_APP_LABEL = "evennia_calendar"
PLOTS_BOARDS_APP_LABEL = "evennia_boards"

######################################################################
# REST API — off by default in the sandbox (no urls.py wiring below);
# flip on and wire web/urls.py if you want the browsable web surfaces.
######################################################################

######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
