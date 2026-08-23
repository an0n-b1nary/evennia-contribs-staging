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
# Part 3 of the playtester plan replaces this handful with a ~16-room, 3-plane
# grid. The slugs are what will carry over.

IC_ENTRY_SLUG = "plaza"

IC_ROOMS = (
    IcRoom(
        slug=IC_ENTRY_SLUG,
        name="Sandbox Plaza",
        desc="[Placeholder] Setting prose. An open square; the hub the other IC rooms hang off.",
        terrain=frozenset({"urban"}),
    ),
    IcRoom(
        slug="archive",
        name="The Archive",
        desc="[Placeholder] Setting prose. A place records are kept; north of the plaza.",
        terrain=frozenset({"urban"}),
    ),
    IcRoom(
        slug="consulate",
        name="Consulate Hall",
        desc="[Placeholder] Setting prose. A formal, official interior; east of the plaza.",
        terrain=frozenset({"urban"}),
    ),
    IcRoom(
        slug="garden",
        name="Garden Walk",
        desc="[Placeholder] Setting prose. Cultivated greenery; west of the plaza.",
        terrain=frozenset({"forest"}),
    ),
    IcRoom(
        slug="overlook",
        name="The Overlook",
        desc="[Placeholder] Setting prose. High ground with a view back over the rest.",
        terrain=frozenset({"hills"}),
    ),
)

IC_ROOMS_BY_SLUG = {room.slug: room for room in IC_ROOMS}

# The one hand-placed tile. Every other IC position is derived by walking
# direction aliases out from here, so this is the room whose coordinates are
# (0, 0) and the one the origin pin sits on.
MAP_ORIGIN_SLUG = IC_ENTRY_SLUG

# (from slug, to slug, (exit key, direction alias), (return key, return alias)).
# The key is what a player types; the alias is what evennia_maps' layout walks.
IC_LINKS = (
    ("plaza", "archive", ("archive", "north"), ("plaza", "south")),
    ("plaza", "consulate", ("hall", "east"), ("plaza", "west")),
    ("plaza", "garden", ("garden", "west"), ("plaza", "east")),
    ("archive", "overlook", ("overlook", "north"), ("archive", "south")),
)

# The boundary: OOC hub <-> IC entry, direction-less on purpose.
IC_BOUNDARY_EXIT_KEYS = ("grid", "arrival")

# One IC exit deliberately carrying no direction alias, so the map visibly does
# not extend through it. This is the thing playtesters trip over, and it is
# better demonstrated than hidden. (from slug, to slug, key, return key)
IC_FLAVOR_LINKS = (("garden", "overlook", "path", "path"),)


# ---------------------------------------------------------------------------
# Django-row content (purged by name, so these names are identity)
# ---------------------------------------------------------------------------

REGION = {
    "slug": "commons",
    "name": "The Commons",
    "description": "[Placeholder] One line describing the region the IC rooms sit in.",
}

PLANE_NAME = "Sandbox Overworld"

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

CALENDAR_EVENT = {
    "slug": "kickoff",
    "title": "Sandbox Kickoff",
    "description": "[Placeholder] One line describing a seeded open event to RSVP to.",
}

SCENES = (
    {
        "slug": "rehearsal",
        "title": "Kickoff Rehearsal",
        "description": "[Placeholder] One line: an open scene in progress.",
        # Deliberately not the entry room: the live-scene glow, the recent-scene
        # heatmap and the upcoming-event marker each need to land on a
        # *different* tile for the overlays to be distinguishable at a glance.
        "room_slug": "consulate",
    },
    {
        "slug": "quiet-hour",
        "title": "A Quiet Hour in the Archive",
        "description": "[Placeholder] One line: a scene that has already ended.",
        "room_slug": "archive",
    },
)

PLAQUE_KEY = "brass plaque"
