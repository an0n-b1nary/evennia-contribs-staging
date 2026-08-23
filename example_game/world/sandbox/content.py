# SPDX-License-Identifier: BSD-3-Clause
"""
Every player-visible string the sandbox seeds, keyed by a stable slug.

**This is the file to edit when you want to change what the demo says.**
`seed_sandbox` imports from here and contains no prose of its own.

Why slugs
---------
The seeder purges Evennia objects (rooms, exits, plain objects) by *tag*, but
plain Django rows - regions, planes, lore entries, boards, scenes - have no tag
handler, so it purges those by *name*. That makes a name a de-facto primary key:
renaming a region between two runs makes the second run fail to find the first
run's row, and the seed stops being idempotent. Slugs are the stable identity;
`name` is free to change without breaking anything.

Placeholders
------------
Room descriptions, plaque text and the connection screen are the game's voice,
and the game's voice belongs to whoever runs it - not to whoever wrote the
seeder. Every such string here is `[Placeholder]` plus a one-line summary of
what it should convey. Replace them; nothing in the code reads their content.

Two things are deliberately *not* placeholders:

- **OOC room names** ("Posing Studio", "Help Desk"). These are signposts to a
  command family rather than fiction, and a playtester has to be able to guess
  where to go. Rename them freely - the slug is what the code holds onto.
- **`commands` lists.** Those are the literal command names a player types, so
  they are documentation, not prose. Keep them accurate; the plaque renders
  from them.

IC rooms get neither a plaque nor a command list. They are meant to read as
setting, and to demonstrate the map and region features structurally - through
terrain, elevation, region membership and overlay data - rather than by
explaining themselves.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OocRoom:
    """A room in the OOC wing: one command family, one plaque, no map tile."""

    slug: str
    name: str
    desc: str
    plaque: str
    commands: tuple = ()


@dataclass(frozen=True)
class IcRoom:
    """A room in the IC world: setting prose, a map tile, region membership."""

    slug: str
    name: str
    desc: str
    terrain: frozenset = frozenset()


# ---------------------------------------------------------------------------
# The OOC wing
# ---------------------------------------------------------------------------
# Laid out hub-and-spoke: ARRIVAL in the middle, every other room one
# direction-less exit away and back. Two moves reaches anything, which is what
# makes eight rooms cheaper to walk than five would be in a line - and lets each
# room carry one command family instead of three.
#
# ARRIVAL is special three ways over: it is dbref #2 (so START_LOCATION and
# DEFAULT_HOME can point at something that survives a reseed), it is the OOC hub
# `+ooc` teleports to, and it is the only room the seeder re-dresses rather than
# creates. See seed_sandbox._spawn_room().

ARRIVAL_SLUG = "arrival"

OOC_ROOMS = (
    OocRoom(
        slug=ARRIVAL_SLUG,
        name="Arrival Hall",
        desc=(
            "[Placeholder] Welcome text. Should convey: this is a demo sandbox, "
            "not a running game; the world resets; every room off this hall "
            "teaches one set of commands; +sandbox explains the rest; the "
            "in-character world is through the one exit that is not a compass "
            "direction."
        ),
        plaque=(
            "[Placeholder] One or two sentences framing the wing as a set of "
            "workshops rather than a place - and saying that reading the plaque "
            "in each room is the intended tour."
        ),
        commands=("+sandbox", "+sandbox/builder on", "+sandbox/builder off"),
    ),
    OocRoom(
        slug="posing",
        name="Posing Studio",
        desc=(
            "[Placeholder] Should convey: this room is for practising how you "
            "speak and act as a character, and that nothing typed here is "
            "permanent or watched."
        ),
        plaque=(
            "[Placeholder] Should convey: poses are the core verb of the whole "
            "game, and the pose tracker tells you whose turn it is in a scene."
        ),
        commands=("+pot", "emit", "semipose", "+poseheader", "+highlight", "+lastpose"),
    ),
    OocRoom(
        slug="scenes",
        name="Scene Room",
        desc=(
            "[Placeholder] Should convey: a scene is a recording of poses that "
            "outlives the moment; this room is where you start one, watch it "
            "collect what you type, and read it back afterwards."
        ),
        plaque=(
            "[Placeholder] Should convey: scenes and the activity tracker are "
            "the same story told twice - one is the transcript, the other is "
            "the credit you get for having been there."
        ),
        commands=("+scene", "+log", "+rptracker", "+activity"),
    ),
    OocRoom(
        slug="social",
        name="Social Commons",
        desc=(
            "[Placeholder] Should convey: this is the room for finding people "
            "and getting to them - who is online, where they are, how to reach "
            "them, and how to be left alone when you want to be."
        ),
        plaque=(
            "[Placeholder] Should convey: half of these commands move you and "
            "half of them find people; +where and +hangouts are the two worth "
            "learning first."
        ),
        commands=(
            "page",
            "+finger",
            "+where",
            "+hangouts",
            "+join",
            "+summon",
            "+home",
            "+ooc",
            "+ignore",
            "+roomconfig",
            "+roulette",
            "@tel",
        ),
    ),
    OocRoom(
        slug="story",
        name="Story Office",
        desc=(
            "[Placeholder] Should convey: this room is about story that is "
            "planned rather than improvised - ongoing plots, the threads inside "
            "them, and the calendar that says when the next one happens."
        ),
        plaque=(
            "[Placeholder] Should convey: a hook is how you advertise a plot to "
            "strangers, and scheduling it on the calendar is how they find it."
        ),
        commands=("+plot", "+arc", "+hook", "+calendar", "+rsvp"),
    ),
    OocRoom(
        slug="lore",
        name="Lore Archive",
        desc=(
            "[Placeholder] Should convey: lore here is discovered rather than "
            "handed over - characters learn things, and can pass what they know "
            "to each other or lose it again."
        ),
        plaque=(
            "[Placeholder] Should convey: +investigate is how you find lore you "
            "do not have yet, and +share is why knowing something is worth more "
            "than reading it."
        ),
        commands=("+lore", "+investigate", "+hint", "+share", "+forget"),
    ),
    OocRoom(
        slug="helpdesk",
        name="Help Desk",
        desc=(
            "[Placeholder] Should convey: this is where you talk to whoever runs "
            "the game rather than to other characters - announcements, requests, "
            "bug reports, and your own progression."
        ),
        plaque=(
            "[Placeholder] Should convey: +bug and +request are the feedback "
            "channel for this sandbox specifically, and they work without any "
            "extra permission."
        ),
        commands=("+bb", "+jobs", "+request", "+bug", "+issue", "+discuss", "+xp"),
    ),
    OocRoom(
        slug="drafting",
        name="Drafting Room",
        desc=(
            "[Placeholder] Should convey: this room is yours to build from - dig "
            "as many rooms off it as you like; they land on a scratch plane of "
            "the map rather than in the in-character world, and the content "
            "reset does not delete them."
        ),
        plaque=(
            "[Placeholder] Should convey the one rule that catches everyone: an "
            "exit only extends the map if its name or one of its aliases is a "
            "compass direction, so @dig north=Somewhere maps and "
            "@dig gate=Somewhere does not. Also: building needs Builder, which "
            "+sandbox/builder on grants on request."
        ),
        commands=("+map", "+region", "@dig", "@tunnel", "+sandbox/builder on"),
    ),
)

OOC_ROOMS_BY_SLUG = {room.slug: room for room in OOC_ROOMS}

# Spokes, in the order they read on the hub's exit list. Each is joined to
# ARRIVAL by a pair of direction-less exits (see OOC_SPOKE_EXIT_KEYS), so
# layout.plan() never walks into the wing even before the unmappable-room-type
# guard gets a say.
OOC_SPOKE_SLUGS = tuple(room.slug for room in OOC_ROOMS if room.slug != ARRIVAL_SLUG)

# The exit key a player types to reach each spoke, and the key back. Keys only -
# deliberately no direction aliases anywhere in this table.
OOC_SPOKE_EXIT_KEYS = {
    "posing": ("posing", "back"),
    "scenes": ("scenes", "back"),
    "social": ("social", "back"),
    "story": ("story", "back"),
    "lore": ("lore", "back"),
    "helpdesk": ("helpdesk", "back"),
    "drafting": ("drafting", "back"),
}

# The scratch plane the Drafting Room sits on, so digging from it grows a map
# without touching the in-character grid. It needs a tile at all because
# evennia_maps' auto-placement listener only fires when the *source* room is
# already mapped (listeners.py) - an unmapped drafting room would make
# `@dig north=X` silently do nothing, which is the exact trap the room exists to
# teach around.
DRAFTING_PLANE_NAME = "Sandbox Scratch"


# ---------------------------------------------------------------------------
# The IC world
# ---------------------------------------------------------------------------
# Reached from ARRIVAL through one direction-less exit - the single boundary
# between the two halves. These rooms carry map tiles and region membership;
# they have no plaques and name no commands.
#
# Seventeen rooms across three planes, and the shape of them is the demo. Read
# IC_GEOGRAPHY below for the whole layout in one place: it is a description of
# what each room is *for* structurally, and every deliberate oddity in it
# (a pinned tile in the wrong cell, a room with no tile, a terrain with no
# sprite) exists to make one feature of the map visible rather than theoretical.

IC_ENTRY_SLUG = "plaza"


# --- Terrain ---------------------------------------------------------------
# Five keys, and the split between them is the point. Four have sprites in
# settings.MAPS_TERRAIN_TILESET; "scrub" deliberately does not, so one tile on
# the grid renders as the plain fallback swatch beside real sprites and the
# difference is visible at a glance. All five are in MAPS_TERRAIN_PRECEDENCE -
# a tag missing from *that* list resolves to no terrain at all (terrain.py),
# which is a different demo, and the Warren covers it by having no tags.

TERRAIN_WATER = "water"
TERRAIN_FOREST = "forest"
TERRAIN_HILLS = "hills"
TERRAIN_SCRUB = "scrub"
TERRAIN_URBAN = "urban"


# --- The overworld: nine rooms, the grid people actually look at -----------

IC_ROOMS = (
    IcRoom(
        slug=IC_ENTRY_SLUG,
        name="Sandbox Plaza",
        desc="[Placeholder] Setting prose. An open square; the hub the rest of the IC world hangs off.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="archive",
        name="The Archive",
        desc="[Placeholder] Setting prose. A place records are kept; north of the plaza.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="overlook",
        name="The Overlook",
        desc="[Placeholder] Setting prose. High ground north of the Archive, looking back over the rest.",
        terrain=frozenset({TERRAIN_HILLS}),
    ),
    IcRoom(
        slug="consulate",
        name="Consulate Hall",
        desc=(
            "[Placeholder] Setting prose. A formal official frontage east of the plaza; "
            "its doors lead somewhere the outdoor map cannot show."
        ),
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="market",
        name="Market Row",
        desc="[Placeholder] Setting prose. A busy commercial street north of the Consulate.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="garden",
        name="Garden Walk",
        desc="[Placeholder] Setting prose. Cultivated greenery west of the plaza.",
        terrain=frozenset({TERRAIN_FOREST}),
    ),
    IcRoom(
        slug="warren",
        name="The Warren",
        desc=(
            "[Placeholder] Setting prose. Somewhere off the Garden Walk that ordinary "
            "visitors are not shown. Should read as deliberately unwelcoming."
        ),
        # No terrain on purpose: this is the blank-terrain tile +map/check lints.
        terrain=frozenset(),
    ),
    IcRoom(
        slug="harbor",
        name="Harbor Steps",
        desc="[Placeholder] Setting prose. Where the plaza meets the water, south of it.",
        # Two tags: MAPS_TERRAIN_PRECEDENCE resolves them to exactly one
        # ("water" outranks "urban"), which is the whole point of having a
        # precedence list rather than a single terrain field.
        terrain=frozenset({TERRAIN_WATER, TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="causeway",
        name="The Causeway",
        desc="[Placeholder] Setting prose. A raised path east from the Harbor Steps, half wild.",
        # The terrain with no sprite. Renders as the fallback swatch.
        terrain=frozenset({TERRAIN_SCRUB}),
    ),
    # --- The undercroft: four rooms, one elevation down --------------------
    # Same zstack as the overworld, elevation -1. Two planes in one zstack is
    # what makes Leaflet draw its base-layer control at all, so this layer
    # exists as much for the control as for the rooms.
    IcRoom(
        slug="cistern",
        name="The Cistern",
        desc="[Placeholder] Setting prose. A flooded chamber directly under the plaza, reached by stairs down.",
        terrain=frozenset({TERRAIN_WATER}),
    ),
    IcRoom(
        slug="tunnel",
        name="Service Tunnel",
        desc="[Placeholder] Setting prose. A worked passage running east from the Cistern.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="vault",
        name="The Vault",
        desc="[Placeholder] Setting prose. A sealed room further along the tunnel.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="sump",
        name="The Sump",
        desc="[Placeholder] Setting prose. The low end of the undercroft, where the water collects.",
        terrain=frozenset({TERRAIN_WATER}),
    ),
    # --- The interior: four rooms on a standalone plane --------------------
    # zstack "" (standalone), so it is not part of the vertical stack and is
    # reached only through a direction-less exit from Consulate Hall. That
    # geometry - an exit onto a plane with a blank zstack - is the entire
    # definition of a portal as far as the map is concerned; there is no
    # portal flag anywhere.
    IcRoom(
        slug="lobby",
        name="Consulate Lobby",
        desc="[Placeholder] Setting prose. Inside the Consulate doors; an interior that is its own small map.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="gallery",
        name="The Gallery",
        desc="[Placeholder] Setting prose. A long hung room off the lobby.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="study",
        name="The Study",
        desc=(
            "[Placeholder] Setting prose. A small room east of the lobby that nobody "
            "has got round to surveying."
        ),
        terrain=frozenset({TERRAIN_URBAN}),
    ),
    IcRoom(
        slug="stair",
        name="The Back Stair",
        desc="[Placeholder] Setting prose. A service stair north of the Gallery.",
        terrain=frozenset({TERRAIN_URBAN}),
    ),
)

IC_ROOMS_BY_SLUG = {room.slug: room for room in IC_ROOMS}


# --- Planes ----------------------------------------------------------------
# Named here rather than left to the map to invent. resolve_stacked_plane()
# will happily scaffold a plane for a `down` exit on its own, but it names it
# after the zstack ("overworld (-1)"), so the undercroft is pre-created with
# the name we want and the walk finds it by (zstack, elevation).

PLANE_NAME = "Sandbox Overworld"
UNDERCROFT_PLANE_NAME = "Sandbox Undercroft"
INTERIOR_PLANE_NAME = "Consulate Interior"

ZSTACK = "overworld"

# {plane name: (zstack, elevation, description)}. The overworld is first
# because it is the one the seeder anchors and walks from.
IC_PLANES = (
    (PLANE_NAME, ZSTACK, 0, "The surface: the grid most of the IC world sits on."),
    (UNDERCROFT_PLANE_NAME, ZSTACK, -1, "One layer down, sharing the surface footprint."),
    (INTERIOR_PLANE_NAME, "", 0, "A standalone interior, reached through the Consulate doors."),
)


# --- The exit graph --------------------------------------------------------
# The one hand-placed tile. Every other overworld and undercroft position is
# derived by walking direction aliases out from here, so this is the room whose
# coordinates are (0, 0) and the one the origin pin sits on.
MAP_ORIGIN_SLUG = IC_ENTRY_SLUG

# The interior is a separate walk with its own anchor, because no direction
# exit reaches it - that is what makes it a portal rather than a neighbour.
INTERIOR_ORIGIN_SLUG = "lobby"

# (from slug, to slug, (exit key, direction alias), (return key, return alias)).
# The key is what a player types; the alias is what evennia_maps' layout walks.
# "down"/"up" are vertical: they cross to the adjacent elevation in the same
# zstack at the *same* (x, y), which is how the undercroft gets placed without
# a single coordinate being written for it.
IC_LINKS = (
    # Overworld
    ("plaza", "archive", ("archive", "north"), ("plaza", "south")),
    ("archive", "overlook", ("overlook", "north"), ("archive", "south")),
    ("plaza", "consulate", ("hall", "east"), ("plaza", "west")),
    ("consulate", "market", ("market", "north"), ("hall", "south")),
    ("plaza", "garden", ("garden", "west"), ("plaza", "east")),
    ("garden", "warren", ("warren", "north"), ("garden", "south")),
    ("plaza", "harbor", ("harbor", "south"), ("plaza", "north")),
    ("harbor", "causeway", ("causeway", "east"), ("harbor", "west")),
    # Down into the undercroft, and along it
    ("plaza", "cistern", ("cistern", "down"), ("plaza", "up")),
    ("cistern", "tunnel", ("tunnel", "east"), ("cistern", "west")),
    ("tunnel", "vault", ("vault", "east"), ("tunnel", "west")),
    ("vault", "sump", ("sump", "east"), ("vault", "west")),
    # Inside the interior. Walked from INTERIOR_ORIGIN_SLUG, not from the
    # plaza - the plaza cannot reach any of this by direction.
    ("lobby", "gallery", ("gallery", "north"), ("lobby", "south")),
    ("lobby", "study", ("study", "east"), ("lobby", "west")),
    ("gallery", "stair", ("stair", "north"), ("gallery", "south")),
)

# The boundary: OOC hub <-> IC entry, direction-less on purpose.
IC_BOUNDARY_EXIT_KEYS = ("grid", "arrival")

# IC exits deliberately carrying no direction alias, so the map does not extend
# through them. (from slug, to slug, key, return key)
#
# The first is a flavor exit inside the overworld: the thing playtesters trip
# over, better demonstrated than hidden. The second is the portal - the doors
# into the Consulate Lobby. Both are "just an exit"; only their destinations
# differ, and it is the *destination plane's* blank zstack that makes the
# second one render a portal marker.
IC_FLAVOR_LINKS = (
    ("garden", "overlook", "path", "path"),
    ("consulate", "lobby", "doors", "out"),
)


# --- Deliberate map defects ------------------------------------------------
# Everything here makes some read-only map tool have something to report. A
# map with nothing wrong with it demonstrates none of the tools that find
# things wrong with maps.

# Rooms whose tiles are re-placed by hand *after* the derived grid is written,
# at coordinates the walk does not agree with. (slug, x, y, pinned)
#
# The whole undercroft reads as a corridor mapped by hand before anyone dug
# the stairs down, and never reflowed since. Running +map/reflow from the
# Cistern reports, and does not silently fix:
#
#   Service Tunnel  wants (1, 0) - held by the pinned Sump  -> blocked_by_pinned
#   The Vault       wants (2, 0) - held by the Tunnel,
#                                  which is itself blocked  -> blocked_by_blocked
#   The Sump        wants (3, 0) - pinned, so never moved at all
#
# The two-step cascade is the part worth seeing: a single validation pass
# would call the Vault's move safe, because the Tunnel *looks* like it is
# about to vacate that cell. Deleted and re-placed rather than moved, because
# these three coordinates are a rotation of the derived ones and there is no
# free cell to start an in-place update from.
MISPLACED_TILES = (
    ("sump", 1, 0, True),
    ("tunnel", 2, 0, False),
    ("vault", 3, 0, False),
)

# Rooms that get no tile at all, though a canonical-direction exit reaches
# them from a room that has one. This is what +map/check's unmapped-neighbour
# lint is for, and it is the ordinary state of a room somebody dug before the
# map existed.
UNMAPPED_SLUGS = ("study",)

# The room typed "staff", which permissions.py hides from the web map, the
# region member list and +where for everyone who is not staff. Toggling
# +sandbox/builder on makes it appear - which is the most direct demo of the
# fail-closed visibility rule there is, because you watch a room exist.
STAFF_ROOM_SLUG = "warren"


# --- Hangouts --------------------------------------------------------------
# The one overlay with no table and no privacy rule behind it: a bare room
# attribute evennia_maps reads duck-typed. Three different types so the
# Hangouts layer shows three different letters rather than proving only that
# the layer switches on. Values must be in evennia_social.HANGOUT_TYPES.
HANGOUTS = {
    "plaza": "plaza",
    "archive": "library",
    "market": "market",
}


# ---------------------------------------------------------------------------
# Django-row content (purged by name, so these names are identity)
# ---------------------------------------------------------------------------

# Three regions, and the interesting one is archived. A room's *flagged*
# primary membership can point at a region that is no longer visible, and the
# map's primary_region overlay deliberately diverges from
# RegionMembership.primary_for() there: it skips archived regions and falls
# through to the room's next membership, because the tile label is a link and
# a link to an archived region is a link to a 404.
#
# So the undercroft rooms are flagged primary in the archived Undercity and
# also belong to the Waterfront, and their tiles label as Waterfront. Unarchive
# the Undercity in the admin and the labels move - that is the demo.
REGIONS = (
    {
        "slug": "commons",
        "name": "The Commons",
        "description": "[Placeholder] One line describing the region most of the surface sits in.",
        "archived": False,
    },
    {
        "slug": "waterfront",
        "name": "The Waterfront",
        "description": "[Placeholder] One line describing the water's edge and what drains into it.",
        "archived": False,
    },
    {
        "slug": "undercity",
        "name": "The Undercity",
        "description": "[Placeholder] One line describing the layer beneath. Archived on purpose.",
        "archived": True,
    },
)

REGIONS_BY_SLUG = {region["slug"]: region for region in REGIONS}

# The region the seeder anchors lore to, so has_lore lights some tiles and not
# others. One region rather than all three: an overlay that is true everywhere
# is indistinguishable from an overlay that is broken.
LORE_REGION_SLUG = "commons"

# {room slug: (primary region slug, (secondary region slugs...))}. Exactly one
# membership per room may carry is_primary - the DB enforces it - so the first
# element is the flagged one and the rest are plain memberships.
#
# Market Row is the room with both: primary in the Commons, secondary on the
# Waterfront, so the region page lists it twice while the tile label stays one
# deterministic answer.
IC_REGION_MEMBERSHIPS = {
    "plaza": ("commons", ()),
    "archive": ("commons", ()),
    "overlook": ("commons", ()),
    "consulate": ("commons", ()),
    "market": ("commons", ("waterfront",)),
    "garden": ("commons", ()),
    "warren": ("commons", ()),
    "harbor": ("waterfront", ()),
    "causeway": ("waterfront", ()),
    # Flagged primary in the archived region; the visible answer is the second.
    "cistern": ("undercity", ("waterfront",)),
    "tunnel": ("undercity", ("waterfront",)),
    "vault": ("undercity", ("waterfront",)),
    "sump": ("undercity", ("waterfront",)),
    "lobby": ("commons", ()),
    "gallery": ("commons", ()),
    "study": ("commons", ()),
    "stair": ("commons", ()),
}

BOARDS = (
    {
        "slug": "general",
        "name": "General",
        "description": "[Placeholder] What this board is for: announcements and OOC chatter.",
    },
    {
        "slug": "cutscenes",
        "name": "Cutscenes",
        "description": "[Placeholder] What this board is for: in-character narrative posts.",
    },
)

BOARD_FIRST_POST = {
    "board_slug": "general",
    "title": "[Placeholder] Title of the seeded welcome post.",
    "body": "[Placeholder] A short first post: what the sandbox is, and that it resets.",
}

LORE_ENTRIES = (
    {
        "slug": "founding",
        "title": "The Founding of the Sandbox",
        "body": "[Placeholder] A short in-world origin story for this place.",
    },
    {
        "slug": "rumors",
        "title": "Rumors from the Archive",
        "body": "[Placeholder] A short rumor entry, the kind +investigate would turn up.",
    },
)

PLOT_ARC = {
    "slug": "genesis",
    "name": "Sandbox Genesis",
    "description": "[Placeholder] One line: the sandbox's default overarching story.",
}

PLOT_THREAD = {
    "slug": "storm",
    "name": "The Founding Storm",
    "description": "[Placeholder] One line: a thread inside the arc, open for hooks.",
}

# Two events, and the second one is the visibility demo: is_staff_event exists
# to stop staff-run events being visible-but-unjoinable to everyone, so the
# calendar overlay withholds it from non-staff. A playtester sees one event on
# the map; the same playtester after +sandbox/builder on sees two.
CALENDAR_EVENTS = (
    {
        "slug": "kickoff",
        "title": "Sandbox Kickoff",
        "description": "[Placeholder] One line describing a seeded open event to RSVP to.",
        "staff_only": False,
        # The scene the event reaches the map through. There is no
        # CalendarEvent -> Room field anywhere in the calendar; a
        # SceneCalendarLink to a scene rooted in a room is the only path.
        "scene_slug": "rehearsal",
    },
    {
        "slug": "briefing",
        "title": "Staff Briefing",
        "description": "[Placeholder] One line describing a staff-run event players cannot join.",
        "staff_only": True,
        "scene_slug": "market-day",
    },
)

CALENDAR_EVENTS_BY_SLUG = {event["slug"]: event for event in CALENDAR_EVENTS}

# Five scenes, distributed unevenly on purpose. The heatmap radius is
# min(4 + 2n, 16), so a grid where every room has one closed scene proves only
# that the layer draws - three rooms at 3 / 1 / 0 proves it *means* something.
#
# "closed" scenes must go through Scene.close(), which is what stamps
# ended_at; the heatmap window filters on ended_at, so a hand-set
# status=CLOSED produces a scene the map never counts.
SCENES = (
    {
        "slug": "rehearsal",
        "title": "Kickoff Rehearsal",
        "description": "[Placeholder] One line: an open scene in progress.",
        # Deliberately not the entry room and not the heatmap room: the live
        # glow, the heatmap and the event marker each need to land on a
        # different tile for the overlays to be distinguishable at a glance.
        "room_slug": "consulate",
        "closed": False,
    },
    {
        "slug": "quiet-hour",
        "title": "A Quiet Hour in the Archive",
        "description": "[Placeholder] One line: a scene that has already ended.",
        "room_slug": "archive",
        "closed": True,
    },
    {
        "slug": "late-shelving",
        "title": "Late Shelving",
        "description": "[Placeholder] One line: another ended scene in the same room.",
        "room_slug": "archive",
        "closed": True,
    },
    {
        "slug": "closing-time",
        "title": "Closing Time",
        "description": "[Placeholder] One line: a third ended scene in the same room.",
        "room_slug": "archive",
        "closed": True,
    },
    {
        "slug": "market-day",
        "title": "Market Day",
        "description": "[Placeholder] One line: a single ended scene somewhere busier.",
        "room_slug": "market",
        "closed": True,
    },
)

SCENES_BY_SLUG = {scene["slug"]: scene for scene in SCENES}

PLAQUE_KEY = "brass plaque"
