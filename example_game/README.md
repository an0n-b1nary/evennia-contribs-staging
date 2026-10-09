# example_game — Contrib Sandbox

A persistent, hand-tested downstream Evennia 6.0 game that installs and wires
together every contrib in this repo. It exists for two reasons:

1. **Reference integration.** It's the "how do these contribs actually get
   wired into a real game" example this repo otherwise lacks — settings,
   cmdsets, server hooks, and the typeclass seams that can't auto-wire.
2. **A living sandbox to hand-test against**, as new contribs (crafting) get
   extracted and land here.

Full design background is tracked separately (local-only planning docs, not
part of this repo).

---

## What's wired up

All 19 current contribs, in dependency order — `evennia_links` first, then `evennia_rp_resources`, then
the apps that depend on it (`evennia_rptracker`, `evennia_scenes`,
`evennia_boards`, `evennia_lore`, `evennia_plots`, `evennia_regions`,
`evennia_maps`), then the standalone apps (`evennia_calendar`,
`evennia_jobs`, `evennia_xp`, `evennia_accessibility`), then the pose/social
layer (`evennia_posing` before `evennia_social` — social hard-depends on
posing), and the RP cluster (`evennia_rp_rules` before `evennia_rp_chargen`,
`evennia_rp_equipment` and `evennia_rp_contest`; equipment requires chargen). See `server/conf/settings.py` for the full `INSTALLED_APPS` list and
every XP/rptracker/lore/boards/plots/regions/maps/posing/social setting.

**Settings hooks point at the contribs' own shipped integration functions**
(`evennia_*.integrations.*`), not at hand-written glue. The table lists the
hooks that point somewhere other than an `integrations` module or are left
out, including the two that stay in `world/sandbox/glue.py`:

| Setting | Wired to |
|---|---|
| `RPTRACKER_FLAG_REVIEW_HOOK` | `evennia_jobs.integrations.staff_review.file_review_job` → a staff-only `+discuss` ticket |
| `BOARDS_ANTIGAMING_REPORTER` | the same jobs reporter |
| `LORE_SESSION_CONTEXT_PROVIDER` | `evennia_lore.integrations.session_context.get_session_context` → room, primary region, plot threads |
| `RPTRACKER_XP_PROJECTION` | `evennia_xp.projection.activity_lines` → projected XP under `+activity` (unset without `evennia_xp`) |
| `RP_RULES_SUBJECT_ADAPTER` | `world/sandbox/glue.py` → chargen sheet, else a sandbox stat block |
| `RP_RULES_VOCABULARY` | `world/sandbox/glue.py` → chargen's DB vocabulary, else ruleset tags |
| plots' `XP_POST_BATCH_HOOKS` entry | omitted — no `flip_thread_flags` equivalent ships |

**Typeclass seams.** `typeclasses/characters.py` and `typeclasses/rooms.py`
mix in `SocialCharacterMixin`/`PosingCharacterMixin` and
`MapsRoomMixin`/`SocialRoomMixin`/`PosingRoomMixin` (social before posing, so
ignore-filtering runs before header/highlight in the cooperative `msg()`
chain — see both contribs' READMEs; `MapsRoomMixin` takes no part in that
chain, so its position is free). Pose/say/emit activity reaches
`evennia_rptracker` and `evennia_scenes` through `evennia_posing`'s
`pose_recorded` signal: `world/sandbox/apps.py` connects it, at server
start, to the single ordered listener in `world/sandbox/glue.py`, which
calls `capture_to_scene`, then `record_rp_activity`, then chargen's
`note_ic_action`. The last call runs after tracking so expiry of an old session
cannot leave the new pose unlocked. OOC text is logged but never locks a build
or counts as IC activity. The one seam that still
can't auto-wire is `Room.at_object_receive` → `evennia_scenes`'
`register_room_entry`, per that contrib's README ("Evennia ships no
room-receive signal; you must call this manually").

Not yet extracted as contribs: crafting. This sandbox will grow to cover it
as it lands.

### Resource gathering

`evennia-rp-resources` 0.1 is wired with a generic Materials / Provisions /
Essences catalogue. The IC rooms already carry forest, hills, urban and water
terrains; these define the open trickle pool, while Grain is always common.
The demonstration characters have Timber holdings and the Proving Grounds
plaque lists `+resources`, `+resources/catalog`, `+gather` and `+gather/clear`.
Rare crystal is excluded from passive accrual and available to staff grants.

Every playable character accrues six units per Monday batch, independently of
RP. A 30-unit base cap tapers only passive income; stocks never decay. The
server-start hook ensures the resources script is running and the character's
cooperative login hook shows one summary after each batch. The summary mixin
would go before DefaultCharacter with no special ordering; the sandbox calls
the summary directly, using the same optional-app pattern as XP. Social's
`SOCIAL_PROFILE_PROVIDERS` adds the gathering lean to `+finger` and respects the
viewer's reveal access. This milestone has no web or API surface.

Staff can preview with `+resources/run dry`, seed/update the configured catalogue,
and grant/spend/audit stock. `+runtime` controls registered settings without a
restart. `RP_RESOURCES_REVEALED=false` hides player access and summaries while
background accrual continues. The live RP suite covers holdings, leans, staff
grants and runtime reveal. `world/sandbox/test_resources.py` checks actual maps,
social and login seams. Fresh CI profiles exclude maps, plots, social or tracker
and verify the excluded package cannot be imported; economy is also asserted
absent until its milestone ships.

### The map, and the web surface

**Every contrib web surface is mounted.** `web/website/urls.py` mounts all
nine; `web/urls.py` mounts the two DRF routers:

| Route | Contrib | What it is |
|---|---|---|
| `/map/`, `/map/<pk>/`, `/map/<pk>/live/` | `evennia_maps` | Plane list, static SVG grid, Leaflet live map |
| `/regions/`, `/regions/<pk>/` | `evennia_regions` | Region list and detail |
| `/scenes/…` | `evennia_scenes` | Scene list, detail, logs |
| `/calendar/…` | `evennia_calendar` | Event list and detail |
| `/plots/…` | `evennia_plots` | Plot list, detail, updates, tags |
| `/boards/…` | `evennia_boards` | Board list, posts, post history |
| `/lore/…` | `evennia_lore` | Compendium, approval queue, version diffs |
| `/jobs/…` | `evennia_jobs` | The queue you triage `+bug` and `+request` from |
| `/xp/` | `evennia_xp` | XP summary |
| `/api/v1/planes/…`, `/api/v1/regions/…` | maps, regions | Read-only DRF feeds; the live map pulls tiles from the first |

**Namespacing differs per contrib, and the wrong choice breaks pages rather
than failing quietly.** `evennia_maps`, `-regions`, `-calendar` and `-plots`
declare `app_name`, so a bare `include()` namespaces them. `evennia_scenes` and
`evennia_boards` reverse through a namespace but declare no `app_name`, so it
is supplied here as an explicit `(module, namespace)` 2-tuple. `evennia_lore`,
`-jobs` and `-xp` reverse their routes **bare** (`{% url 'lore-list' %}`) and
must be mounted *without* a namespace — wrapping them would make every link in
their templates a `NoReverseMatch`. `TestEveryWebSurfaceIsMounted` in
`world/sandbox/tests.py` reverses and fetches all nine landing pages, which is
the only place that can catch a wrong choice: a contrib's own suite mounts a
URLconf containing that contrib alone.

Scenes and calendar would earn their mounts even if nothing else did:
`evennia_maps.overlays.overlay_url_templates()` reverses
`evennia_scenes:scene-detail` and `evennia_calendar:calendar-event-detail`
and silently drops whichever does not resolve, so without those two includes
the tile popups would list recent logs and upcoming events as plain text.

**Six tile overlays, zero overlay settings.** `evennia_maps` knows where rooms
are and nothing else. Once per map render it sends `collect_tile_overlays`,
and `evennia_regions` (`primary_region`), `evennia_scenes`
(`has_active_scene`, `recent_scene_count`, `recent_scenes`), `evennia_lore`
(`has_lore`) and `evennia_calendar` (`upcoming_events`) each answer for the
rooms they know about, from providers they connect themselves in their own
`AppConfig.ready()`. Nothing in `settings.py` configures this — uninstall a
partner and its layer is simply absent. `world/sandbox/tests.py`
(`TestMapOverlaySeam`) is the end-to-end proof, and it can only live here: no
contrib's own suite installs the other three.

### Native website pages and client shell

`web/website/urls.py` shadows Evennia's native Help index and detail, Channels,
Characters, and Manage Characters routes while leaving their URL shapes and
the remaining edit and account flows intact. They use the same wide
`website/base.html` frame, and any list that paginates includes its own pager
so pages without a list stay uncluttered. Help keeps Evennia's original detail
URLs, merges the displayed `Comms` label into `Communication`, preserves
command spelling on both index and detail pages, and searches topic, category,
and body text. The `Building`, `Staff`, `Admin`, and `System` categories are
hidden from non-Builders, including direct detail requests.

`EVENNIA_WEB_STAFF_LOCK` is the game-level, fail-closed lock used for those
categories and the staff menu. It defaults to `cmd:perm(Builder)` and is
deliberately independent of Django's `is_staff` flag; Django Admin remains
gated by that separate Django flag. The `/api/v1/` browsable root also has a
local template whose optional schema links fail quietly when those routes are
not installed. The webclient keeps Evennia's normal client
scripts and layout, with a reserved link back to the site, an 80-character
reading measure, and a smaller default input pane. Existing browser-local
layout preferences are not rewritten.

### The seeded world: an OOC wing and an IC grid

The world is in two halves, and the split is the tutorial.

**The OOC wing** is nine rooms, hub-and-spoke off the **Arrival Hall**, which
is also where new characters spawn and where `+ooc` returns you. Each spoke
carries one command family and one brass plaque naming its commands:

| Room | Contribs | Commands |
|---|---|---|
| Arrival Hall | — | `+sandbox`, `+sandbox/builder` |
| Posing Studio | `evennia_posing` | `+pot`, `emit`, `semipose`, `+poseheader`, `+highlight`, `+lastpose` |
| Scene Room | `-scenes`, `-rptracker` | `+scene`, `+log`, `+rptracker`, `+activity` |
| Social Commons | `-social` | `page`, `+finger`, `+where`, `+hangouts`, `+join`, `+summon`, `+home`, `+ooc`, `+ignore`, `+roomconfig`, `+mood`, `+roulette`, `@tel` |
| Story Office | `-plots`, `-calendar` | `+plot`, `+arc`, `+hook`, `+calendar`, `+rsvp` |
| Lore Archive | `-lore` | `+lore`, `+investigate`, `+hint`, `+share`, `+forget` |
| Help Desk | `-jobs`, `-boards`, `-xp` | `+bb`, `+jobs`, `+request`, `+bug`, `+issue`, `+discuss`, `+xp` |
| Drafting Room | `-maps`, `-regions` | `+map`, `+region`, `@dig`, `@tunnel` |
| Proving Grounds | `-rp-rules`, `-rp-chargen`, `-rp-equipment`, `-rp-contest` | `+sheet`, `+stats`, `+pips`, `+abilities`, `+spend`, `+upgrade`, `+lock`, `+unlock`, `+test`, `+chargen`, `+gear`, `+wear`, `+remove`, `+worn` |

### RP checks in the Proving Grounds

Take `proving` from the Arrival Hall and read the plaque. The seven stats are
Strength, Endurance, Agility, Intellect, Intuition, Presence and Resolve. A simple
starting sheet sets every stat to B (14 allocation points), then finalizes:

```text
+stats Strength=B
+stats Endurance=B
+stats Agility=B
+stats Intellect=B
+stats Intuition=B
+stats Presence=B
+stats Resolve=B
+stats/finalize
+pips/set Intellect=3
+pips/set Agility=2
+spend/ability Proficiency:Athletics
+upgrade Proficiency:Athletics
+sheet
+test/list
+test #2=Agility/Athletics~I leap across.
```

Domains suggest an approach in their descriptions; any stat/tag pairing is
legal. The second tag kind is fighting styles: Blades, Blunt, Polearms,
Archery, Unarmed and Spellcraft. A move would have a style, and any test may
carry one. The seeded Storyteller has Proficiency:Performance, the Visitor has
Combat Focus:Blades, and both have finalized sheets and a flaw. Builder mode lets you
inspect them with `+sheet <name>`. The Stat-block Dummy has C in every stat
and no chargen sheet; puppet it to exercise the adapter fallback.

Challenge #1 suggests Presence/Performance at A; #2 is the prompt-only B
challenge “Cross the chasm.” Choose a different approach with
`+test #1=Intellect/Deception`; the result marks it as an alternative. Anyone can
set a challenge, including `+test/set/once B~Cross the chasm`. Its setter or
staff can edit, void attempts, and close it. Room messages and public scene
logs show outcomes; grades stay private and only staff `+test/review` sees
dice and the resolution ledger.

IC poses and checks lock pips and the ability loadout. `+unlock` announces
your change; the next IC pose locks again. An OOC message does not lock the
build. Tracker session end or three idle hours releases it. Abilities use
a 100-point loadout; Proficiency and Combat Focus cost 10 each, flaws cost none.
The starting allowance is 10, acquisitions cost 3, and upgrades cost 2, 4,
8, then 16. Purchases use the allowance first, then earned XP. To top up for
playtesting, run `+sandbox/builder on`, then `+xp/grant <character>=10:Playtest`.
`+spend` shows both balances. Staff can revoke with an exact refund using
`+chargen/revoke/refund <character>/<ability>:<tag>`.

**Practice gear.** Equipment grants nothing; it asks a build to commit. The
Proving Grounds floor holds a travelling cloak that asks for nothing and a
heavy maul that asks for Strength `++`. The Storyteller wears duelist's gloves
(Agility `++`) and the Visitor a blade charm (Combat Focus:Blades equipped),
so `look Storyteller` shows a *Wearing* section and the gloves leave the
"You see" list. Try `+gear/info maul`, then make your own:

```text
+gear/make Cursed Axe=weapon
+gear/line axe=a cursed axe of black iron
+gear/require axe=Agility +2
+wear axe
+pips/set Agility=1
```

The last line is refused: *Agility ++ is held by your Cursed Axe. Take that
off first.* Staff get the same refusal; there is no override. `+remove axe`
frees the pips. Wearing and removing freeze with the build lock, and worn gear
can't be dropped or given. An ability you don't own yet only marks the gear
"not fully attuned". Only an item's maker can change it, until someone else
has held it. `at_server_start()` logs any worn gear whose requirements no
longer resolve; `+gear/audit` lists the same for staff.

The Character typeclass calls the contrib's display helpers rather than mixing
in `EquipmentCharacterMixin`, because equipment requires chargen and is absent
whenever chargen is.

Every name above belongs to the game, not the contribs. Stats, domains, styles
and abilities are named in `world/ruleset.py`. The sheet's nouns (pips,
weakness, loadout, points) are set in the RP block of `server/conf/settings.py`,
and their contrib defaults are listed there. To rename a command such as
`+pips`, follow "Renaming things for your game" in the
[rp-chargen README](../contribs/rpg/evennia_rp_chargen/README.md#renaming-things-for-your-game).

The CI `rp-sandbox` job runs the full sandbox gate with all partners, then
fresh environments with scenes, tracker, XP, chargen, equipment or contest
physically absent (equipment leaves with chargen, which it requires). For a local drill, create a fresh venv, install Evennia 6.0.0, and use
`ci_install_contribs.py <install-game> --exclude <distribution>` before
`ci_run_rp_sandbox_tests.py <new-game-dir> --absent <app_label>`.
The runner verifies the package is unimportable, copies the sandbox without
databases or secrets, and requires a positive test count. Without chargen,
stat blocks and ruleset tags still work; without contest, sheet commands do;
without equipment, no gear is seeded and `look` shows no *Wearing* section.

`evennia_accessibility` and `evennia_links` get no room: the first has one
command, `+screenreader`, mounted on the *account* cmdset so it works anywhere
(including before puppeting), and is otherwise web/MXP-side; the second is a
pure seam library.

**The IC world** is reached through the single direction-less `grid` exit from
the hall: seventeen rooms on three planes, mapped, region-membered, and
carrying no plaques. They are meant to read as setting and to demonstrate the
map structurally — through terrain, elevation, region membership and overlay
data — rather than by explaining themselves.

| Plane | zstack / elev | Rooms | What it exists to show |
|---|---|---|---|
| `Sandbox Overworld` | `overworld` / `0` | 9 | The main grid: terrain variety, hangouts, scenes, the staff room |
| `Sandbox Undercroft` | `overworld` / `-1` | 4 | Two planes in one zstack, which is what makes Leaflet draw its base-layer control at all |
| `Consulate Interior` | `""` / `0` | 4 | A standalone plane reached through a portal, and cross-plane click-through |

**Almost nothing in that grid has a coordinate written for it.** The seeder
places two tiles by hand — one origin per walk — and derives everything else by
walking canonical-direction exit aliases with `layout.plan()` /
`apply_plan()`. The undercroft comes along for free, because `down` is a
*vertical* direction and the same walk crosses into the adjacent elevation at
the same `(x, y)`. Seeding this way means a broken alias shows up as a missing
tile rather than as a silently wrong-but-placed grid, and it exercises the same
code path a builder's `+map/reflow` does.

**The interior is a second, separate walk**, because nothing reaches it by
direction: the `doors` from Consulate Hall are a plain exit. That is the entire
definition of a portal as far as the map is concerned — an exit onto a plane
whose zstack is blank. There is no portal flag anywhere.

#### The deliberate defects

A map with nothing wrong with it demonstrates none of the tools that find
things wrong with maps. Four things are wrong with this one on purpose, and
`world/sandbox/content.py` indexes them under "Deliberate map defects":

- **The undercroft is misaligned.** Three tiles sit at coordinates the walk
  disagrees with, with the squatter pinned, so `+map/reflow` from the Cistern
  reports a two-step cascade rather than silently rearranging: the Service
  Tunnel is `blocked_by_pinned`, and the Vault is `blocked_by_blocked` because
  the Tunnel that holds its target cannot vacate. The second step is the part
  worth seeing — a single validation pass would call the Vault's move safe.
- **The Study has no tile**, though a canonical `east` exit reaches it from the
  mapped Lobby. That is the ordinary state of a room dug before anyone drew a
  map, and it is what `+map/check`'s unmapped-neighbour lint is for.
- **The Warren has no terrain**, which is the other thing `+map/check` lints.
  The Causeway has a terrain (`scrub`) with no sprite in
  `MAPS_TERRAIN_TILESET`, so it draws the plain fallback swatch beside real
  sprites. Those two absences look identical on a rendered grid unless you know
  to tell them apart, so the tests assert them apart.
- **The Undercity region is archived**, and the undercroft rooms' *flagged*
  primary membership is in it. `RegionMembership.primary_for()` still answers
  "the Undercity"; the map's overlay deliberately diverges, skips archived
  regions and falls through to the Waterfront — because a tile label is a link,
  and `RegionDetailView` resolves through `Region.objects`, so honouring the
  flag would render a link straight to a 404.

Two more arrangements are worth knowing about. **Harbor Steps carries two
terrain tags** (`water` and `urban`), which is the only room that makes
`MAPS_TERRAIN_PRECEDENCE` do any work. **The Warren is `room_type="staff"`** —
unlike the OOC wing it *is* placed on the grid, and it is the read side that
withholds it, so a playtester can watch a room appear by running
`+sandbox/builder on`. That is the most direct demonstration of the fail-closed
visibility rule there is.

**Three things keep the wing off the map**, and the redundancy is deliberate:
every wing exit is direction-less (so `layout.plan()`, a *read* path, never
walks in); every wing room is `room_type="ooc"` and
`MAPS_UNMAPPABLE_ROOM_TYPES = ("ooc",)` (so the auto-placement listener, a
*write* path, refuses even when somebody digs a real direction); and no wing
room is given a region membership.

**The Drafting Room is the one exception, on purpose.** It holds a pinned tile
on a second plane, `Sandbox Scratch`, because `evennia_maps`' auto-placement
listener only fires when the room being dug *from* is already mapped — an
unmapped drafting room would make `@dig north=X` a silent no-op, which is the
exact trap the room exists to teach around. A separate plane means playtester
experiments never collide with the IC grid. `+map/check` reports that tile,
which is the honest outcome: the setting guards the listener, not the explicit
write path the seeder uses.

**Two rooms and one plane survive `+sandbox/reset`.** The Arrival Hall (it is
dbref `#2`, which is what `START_LOCATION` must point at) and the Drafting Room
plus its scratch plane — because rooms a playtester digs hang off that room,
and purging it would cascade their exits away and orphan everything they built.
They carry `STABLE_TAG` rather than `SANDBOX_TAG`, and `_stray_rooms()` in
`commands/sandbox.py` counts against both tags so the "rooms made by hand"
number still reads zero on an untouched sandbox.

#### Terrain sprites

`web/static/sandbox/terrain/` holds four 32×32 flat-colour PNGs, ~100 bytes
each, named by `MAPS_TERRAIN_TILESET` in `server/conf/settings.py`. **They are
placeholders, not art** — they exist so the map has something to draw that is
visibly *not* the fallback swatch, which is the only way to demonstrate the
tileset does anything. Replace them with real tile art of the same dimensions
and nothing else changes. Deleting the setting entirely is also supported: the
map then draws every tile as a fallback swatch.

There is deliberately no `scrub.png`, so one tile on the grid always renders
the fallback. Adding one would remove that demonstration.

### Editing what the demo says

**All player-visible prose lives in `world/sandbox/content.py`**, keyed by
stable slug. `seed_sandbox.py` imports from it and contains no prose at all.

The split exists because the two halves have different lifetimes. The seeder
purges Evennia objects by *tag*, but plain Django rows — regions, planes, lore,
boards, scenes — have no tag handler and are purged by *name*, which makes a
name a de-facto primary key: rename a region between runs and the second run
cannot find the first run's row, so the seed stops being idempotent. Slugs are
the stable identity; names and descriptions are free to change.

Every description, plaque and the connection screen ships as `[Placeholder]`
plus a one-line summary of what it should convey. Room *names* and the
`commands` lists are not placeholders — the first are signposts a playtester
has to be able to guess, the second are literal command names, so both are
documentation rather than voice.

**Renaming rooms is safe; renaming the Django rows is not.** Every room lookup
in the seeder and its tests goes through a slug, and the few name-derived
constants (`MAPPED_ROOM_NAMES`, `ORIGIN_ROOM_NAME`, `OOC_ROOM_DBREF`) are all
*computed* from `content.py` rather than restated, so a rename follows through
on the next reseed. Region, plane, board, lore, scene, plot and event **names**
are the exception: those rows have no tag handler and the purge finds them by
name, so renaming one without reseeding first leaves the old row behind and the
next run collides on a unique name. Change the name, reseed, done.

Two smaller consequences of renaming a room *in-game* rather than in
`content.py`: `RoomTile.room_name` and `RegionMembership.room_name` are
denormalized display snapshots that only refresh when the tile or membership is
rewritten, so the web map keeps showing the old name until the next reseed.

### Playtester controls (`+sandbox`)

`commands/sandbox.py` is the game's only local command, and it is demo-only
glue no real game should copy: `+sandbox/builder on` adds the `Builder`
permission to the caller's own account and puppet, `off` removes it.

Every contrib defaults its staff lock to `perm(Builder)` (the `*_STAFF_LOCK`
block in `server/conf/settings.py`), so this one toggle is the whole staff/
player split. It is a toggle rather than a blanket promotion precisely
because the player half — the lore approval queue seen from the submitting
side, the anonymised job submitter, read-only boards, the `+plot`/`+arc`
divide — is half of what there is to demo.

Two things the command's own output says, worth repeating here:

- **A superuser bypasses every lock**, so `+sandbox/builder off` will not
  show Account #1 the player experience. `quell` first (`unquell` to
  restore) — which is also why the toggle writes the permission to the puppet
  as well as the account: under quell, Evennia's `perm()` takes the *minimum*
  of the two.
- **Only `+jobs`, `+discuss` and `+rptracker` are locked at the class level.**
  Every other contrib is `cmd:all()` and checks its staff lock inside
  `func()`, so those three are the ones that visibly appear and disappear
  from `help` as the toggle flips.

`+sandbox/reset` is held at `perm(Admin)` — deliberately above what the
toggle hands out, since a Builder-level gate would be no gate at all when
anyone can become a Builder. See [Resetting](#resetting).

---

## Local dry-run (before touching the droplet)

You can validate the wiring on your own machine first — same steps as the
droplet, just without nginx/systemd/TLS:

```bash
python3.12 -m venv .venv_sandbox   # NOT the same venv as any other Evennia game;
                                   # Evennia 6.0 runs on 3.10-3.12 (any works)
source .venv_sandbox/bin/activate  # or .venv_sandbox\Scripts\activate on Windows
pip install "evennia>=6.0"
for d in contribs/base_systems/evennia_links \
         contribs/game_systems/evennia_rp_resources \
         contribs/game_systems/evennia_rptracker \
         contribs/game_systems/evennia_scenes \
         contribs/game_systems/evennia_boards \
         contribs/game_systems/evennia_lore \
         contribs/game_systems/evennia_plots \
         contribs/game_systems/evennia_regions \
         contribs/game_systems/evennia_maps \
         contribs/game_systems/evennia_calendar \
         contribs/game_systems/evennia_jobs \
         contribs/game_systems/evennia_xp \
         contribs/utils/evennia_accessibility \
         contribs/game_systems/evennia_posing \
         contribs/game_systems/evennia_social \
         contribs/rpg/evennia_rp_rules \
         contribs/rpg/evennia_rp_chargen \
         contribs/rpg/evennia_rp_equipment \
         contribs/rpg/evennia_rp_contest; do
    pip install -e "$d"
done
cd example_game
evennia migrate
evennia start   # create the superuser when prompted
evennia seed_sandbox
```

Connect with a telnet client to `localhost:4100` and run through the
Verification checklist below — telnet is the local smoke-test path. The
webclient at `http://localhost:4101` loads, but its websocket points at
`WEBSOCKET_CLIENT_URL` (the production subdomain), so the in-page client
won't fully connect until you're deployed behind nginx with the real
hostname set.

---

## Droplet deployment

This droplet already runs a separate, unrelated Evennia **3.x** game on the
default ports. Two things keep the sandbox from interfering with it:

- **A strictly isolated Python 3.10–3.12 venv.** Different Evennia major
  version, different Django/dependency tree — never `pip install` into the
  other game's environment, and never activate its venv while working on this
  one.
- **A shifted port block** (see `server/conf/settings.py`): telnet `4100`,
  webclient `4102`, webserver proxy/internal `4101`/`4105`, `AMP_PORT`
  `4106`. `AMP_PORT` is the one that's easy to forget — it's "internal" but
  still binds a real TCP port on the host, and the default `4006` collides
  with the other game.

The droplet has so far only been accessed as root. This sandbox is a
public-facing service sharing the host with another game, so it runs as a
**dedicated non-root user** — a compromise of the game process should not be
a compromise of the whole box (or the other game).

### 0. Create the service user (as root)

```bash
adduser --disabled-password contrib_sandbox
sudo -iu contrib_sandbox
# Everything below runs as contrib_sandbox. sudo is only needed again for
# steps 7 (systemd) and 8 (nginx/certbot).
```

### 1. Isolate

Evennia 6.0 runs on Python **3.10, 3.11, or 3.12** — any works; use whatever
your OS provides most easily.

```bash
python3.12 -m venv ~/sandbox/venv        # or python3.11 / python3.10
source ~/sandbox/venv/bin/activate
pip install "evennia>=6.0"
```

**If the OS has no suitable Python** — e.g. Ubuntu 20.04 ships only 3.8, and the
deadsnakes PPA can silently refuse to serve newer builds (apt reports "Unable to
locate package python3.12" even with the PPA added and its key accepted) — don't
fight apt; build one from source with **pyenv**. As root, install the build
toolchain:

```bash
sudo apt install -y make build-essential libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev libffi-dev liblzma-dev wget curl git \
  tk-dev libncursesw5-dev xz-utils
```

`libssl-dev`, `libsqlite3-dev`, and `libffi-dev` are load-bearing for Evennia
(TLS, the SQLite DB, cffi) — omit them and Python still compiles but silently
lacks those modules. Then as `contrib_sandbox`:

```bash
curl -fsSL https://pyenv.run | bash
cat >> ~/.bashrc <<'PYENV'

export PYENV_ROOT="$HOME/.pyenv"
[ -d "$PYENV_ROOT/bin" ] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
PYENV
exec bash
pyenv install 3.12.8
~/.pyenv/versions/3.12.8/bin/python -m venv ~/sandbox/venv
source ~/sandbox/venv/bin/activate
```

`pyenv install` prints `Installing...` and then goes **silent for several
minutes while it compiles — it is not frozen.** Confirm progress from a second
shell with `tail -f /tmp/python-build.*.log`, and keep an eye on `free -h` (a
source build can OOM a 1 GB droplet). Once the venv exists, pyenv's job is done —
nothing downstream (or the systemd unit) depends on it; they all call
`~/sandbox/venv/bin/…` directly.

**Keep the venv activated** for every interactive step below (migrate, start,
seed). If pip ever says *"Defaulting to user installation because normal
site-packages is not writeable"*, the venv is **not** active — pip has fallen
back to the system Python, and `evennia>=6.0` will look uninstallable ("no
matching distribution") only because that system Python is too old. Re-run
`source ~/sandbox/venv/bin/activate` and check `python --version`.

### 2. Clone this repo — pull-only, and make it structurally so

```bash
git clone https://github.com/an0n-b1nary/evennia-contribs-staging.git ~/sandbox/evennia-contribs-staging
cd ~/sandbox/evennia-contribs-staging
git config pull.ff only
git remote set-url --push origin DISABLED-pull-only
```

**The droplet never authors anything.** It pulls; it does not commit and does not
push. If something here needs to change, change it in a local clone and pull the
result. Genuinely machine-specific state is the exception, which is why
`server/conf/secret_settings.py` is gitignored — that is the pattern to follow for
anything else local to this box.

Those two config lines are what make the rule hold on its own:

- `pull.ff only` makes `git pull` refuse anything that isn't a fast-forward. Without
  it, a single commit made here quietly turns every later pull into a merge, and the
  branches diverge further each time. With it, you find out on the first pull.
- `set-url --push` breaks pushes at the remote level. Fetch and pull keep working;
  `git push` fails immediately instead of prompting for credentials that shouldn't be
  on this machine anyway. (GitHub dropped password auth for Git in 2021, so an
  interactive push here fails regardless — this just makes it fail *clearly*.)

If the droplet has already diverged, it is carrying a commit of its own. Confirm and
discard it:

```bash
git fetch origin
git log --oneline origin/main..HEAD   # what this box has that origin doesn't
git status --short                    # any modified tracked files?
git reset --hard origin/main          # discards the above
```

`--hard` is safe here **only because everything that matters on this box is
gitignored** and therefore untouched: `server/evennia.db3`, `server/conf/
secret_settings.py`, and `server/logs/`. Check `git status --short` first anyway —
if it lists a modified tracked file, that change is real and reset will destroy it.

### 3. Install the contribs, in dependency order

```bash
for d in contribs/base_systems/evennia_links \
         contribs/game_systems/evennia_rp_resources \
         contribs/game_systems/evennia_rptracker \
         contribs/game_systems/evennia_scenes \
         contribs/game_systems/evennia_boards \
         contribs/game_systems/evennia_lore \
         contribs/game_systems/evennia_plots \
         contribs/game_systems/evennia_regions \
         contribs/game_systems/evennia_maps \
         contribs/game_systems/evennia_calendar \
         contribs/game_systems/evennia_jobs \
         contribs/game_systems/evennia_xp \
         contribs/utils/evennia_accessibility \
         contribs/game_systems/evennia_posing \
         contribs/game_systems/evennia_social \
         contribs/rpg/evennia_rp_rules \
         contribs/rpg/evennia_rp_chargen \
         contribs/rpg/evennia_rp_equipment \
         contribs/rpg/evennia_rp_contest; do
    pip install -e "$d"
done
```

### 4. Set the real hostname, migrate, first boot

Put the real subdomain in `server/conf/secret_settings.py`, which Evennia
gitignores by default. This keeps the real domain out of every tracked file —
`settings.py` keeps its committed `sandbox.YOURDOMAIN` placeholder — so there's
nothing for the anonymity guard to catch and no risk of committing it by hand.
Because the four dependent values are derived from `SANDBOX_HOSTNAME` at
definition time in `settings.py`, override them here too:

```bash
cd example_game
tee server/conf/secret_settings.py > /dev/null <<'SECRET'
SANDBOX_HOSTNAME = "sandbox.YOURDOMAIN"
ALLOWED_HOSTS = [SANDBOX_HOSTNAME, "localhost", "127.0.0.1"]
SERVER_HOSTNAME = SANDBOX_HOSTNAME
WEBSOCKET_CLIENT_URL = f"wss://{SANDBOX_HOSTNAME}/ws"
CSRF_TRUSTED_ORIGINS = [f"https://{SANDBOX_HOSTNAME}"]
SITE_URL = f"https://{SANDBOX_HOSTNAME}"
SECRET
# then edit the first line to your real subdomain
```

Confirm it's ignored (`git check-ignore server/conf/secret_settings.py` should
echo the path back), and that **every line is flush-left** — a stray leading
space gives `IndentationError: unexpected indent` on boot. Then:

```bash
evennia migrate
evennia start   # create the superuser when prompted
```

The migrate and interactive superuser creation **must be done by hand here.**
systemd (step 7) has no stdin to answer the superuser prompt, so first boot
cannot be left to the service — do it now, then hand the running game to systemd.

### 5. Seed content

```bash
evennia seed_sandbox   # rerunnable; idempotent
```

### 6. Snapshot the golden DB

The RP playtest restores the golden baseline. Generate it from a fresh local
database after each migration change. The snapshot builder copies the game
without existing databases or secret settings, migrates, creates a single
purpose-made `admin` account with an empty email and a random password, seeds
the sandbox, and checks the result before writing the snapshot:

```bash
python example_game/scripts/snapshot_golden.py
```

The generated credentials are saved under the gitignored `ci_game/` directory;
move the password into your password manager. This command never reads the live
database or changes an existing account. Keep production password hashers.

**The golden snapshot is generated locally, not on the droplet, and the droplet
never pushes.** It is committed as `server/evennia_default.db3`; the droplet only
ever pulls it. Re-snapshot after every `evennia migrate` and commit the result.

Why local rather than from the deployed sandbox, which is the more obvious choice:
a snapshot taken from the droplet carries that server's real `accounts_accountdb`
rows into a public repo — the superuser's email and password hash. Worse, a golden
reset *restores* those rows, so the published hash is the live sandbox's admin
credential after every reset, and an Evennia superuser has `@py`. Generating locally
with a purpose-made account keeps production credentials out of the repo entirely.

Two rules follow from the file being public:

- **The password must be high-entropy** (28+ random characters) and stored in a
  password manager, because its hash is published. Changing it means re-snapshotting.
- **The account must have an empty email.** The snapshot builder checks the
  account, production hasher, SQLite integrity and foreign keys, and scans the
  binary for the local anonymity patterns. Ordinary pre-commit text hooks do
  not scan `.db3`. You can also inspect the result before committing:

```bash
python - <<'SCAN'
import re
d = open('server/evennia_default.db3','rb').read()
print('emails :', set(re.findall(rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}', d)))
print('hostname:', b'sandbox.' in d)
SCAN
sqlite3 server/evennia_default.db3   "SELECT id,username,email,is_superuser FROM accounts_accountdb;"
```

Expect no emails and exactly one account: `admin`, blank email, superuser, with a
`pbkdf2_sha256$` hash. An `md5$` hash means the DB was built under `test_settings.py`
and must be rebuilt — that hasher is for tests only and would be trivially crackable
once published.

### 7. systemd (as root / via sudo)

Do steps 4–5 (migrate, first boot + superuser, seed) on the droplet **before**
this — systemd is last because it can't handle the interactive first boot.
Step 6 is not a droplet step at all: the golden snapshot is built and committed
from a local clone, and the droplet picks it up with `git pull`.

```ini
# /etc/systemd/system/evennia-sandbox.service
[Unit]
Description=Evennia contrib sandbox (example_game)
After=network.target

[Service]
Type=forking
User=contrib_sandbox
# REQUIRED: systemd runs with a bare PATH that does NOT include the venv's bin.
# Evennia's launcher shells out to `twistd`, which lives in the venv — without
# this line it dies with "No such file or directory: 'twistd'" and the service
# never starts. The venv bin must come first.
Environment=PATH=/home/contrib_sandbox/sandbox/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WorkingDirectory=/home/contrib_sandbox/sandbox/evennia-contribs-staging/example_game
ExecStart=/home/contrib_sandbox/sandbox/venv/bin/evennia start
ExecStop=/home/contrib_sandbox/sandbox/venv/bin/evennia stop
PIDFile=/home/contrib_sandbox/sandbox/evennia-contribs-staging/example_game/server/portal.pid
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now evennia-sandbox
sudo systemctl status evennia-sandbox     # want: active (running)
```

If it sits at `activating (start)` with **Tasks: 1** and no listening ports,
it's stuck, not slow — read `journalctl -u evennia-sandbox -n 40`. The usual
cause is the missing `Environment=PATH` above (the `twistd` error); the other is
that step 4's manual migrate/first-boot was skipped.

### 8. nginx + TLS (as root / via sudo)

**First check whether port 80 is already taken** — on a shared box the other
game may serve its own web directly:

```bash
ss -ltnp | grep -E ':80 |:443 '
```

#### Case A — port 80 is free

Standard flow: a vhost on 80, then `certbot --nginx` (it adds the 443 listener,
the cert, and an 80→443 redirect for you).

```nginx
# /etc/nginx/sites-available/evennia-sandbox
server {
    server_name sandbox.YOURDOMAIN;
    listen 80;

    location /ws {
        proxy_pass http://127.0.0.1:4102;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
    location / {
        proxy_pass http://127.0.0.1:4101;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`X-Forwarded-Proto` lets Django see the original HTTPS scheme through the proxy —
without it, secure POSTs (web-admin / login) fail CSRF with a 403. It pairs with
`SECURE_PROXY_SSL_HEADER` + `CSRF_TRUSTED_ORIGINS` on the app side (steps 4 & B).

```bash
ln -s /etc/nginx/sites-available/evennia-sandbox /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d sandbox.YOURDOMAIN
```

#### Case B — port 80 is already held (the shared-droplet case)

You can't bind 80 or use certbot's default http-01 challenge, and you must NOT
reconfigure the running game. Run nginx on **443 only** and validate the cert
via a **DNS challenge**.

1. Issue the cert with DNS-01 (needs no port 80):

   ```bash
   certbot certonly --manual --preferred-challenges dns -d sandbox.YOURDOMAIN
   ```

   It pauses and gives you a TXT record to create: name `_acme-challenge.sandbox`
   (**just that** — your DNS host appends the domain automatically; typing the
   full `_acme-challenge.sandbox.YOURDOMAIN` doubles it and the lookup fails),
   value = the string shown. Add it at your DNS host, then — before pressing
   Enter — confirm from another shell, querying a public resolver to dodge
   negative caching (propagation can lag minutes or more):

   ```bash
   dig +short TXT _acme-challenge.sandbox.YOURDOMAIN @8.8.8.8
   ```

2. Write a **443-only** vhost using the issued cert (no `listen 80`):

   ```nginx
   # /etc/nginx/sites-available/evennia-sandbox
   server {
       listen 443 ssl;
       server_name sandbox.YOURDOMAIN;

       ssl_certificate     /etc/letsencrypt/live/sandbox.YOURDOMAIN/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/sandbox.YOURDOMAIN/privkey.pem;

       location /ws {
           proxy_pass http://127.0.0.1:4102;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
       }
       location / {
           proxy_pass http://127.0.0.1:4101;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

   (`X-Forwarded-Proto` is required for the app-side CSRF fix — see step 4's
   `secret_settings.py` and `SECURE_PROXY_SSL_HEADER` in `settings.py`. Without
   it, the web-admin/login POST fails CSRF with a 403.)

3. Enable it and — crucially — **disable any default vhost that listens on 80**,
   or nginx won't start at all. A single `listen 80` colliding with the other
   game aborts the *entire* nginx process, including your valid 443 site:

   ```bash
   ln -sf /etc/nginx/sites-available/evennia-sandbox /etc/nginx/sites-enabled/
   rm -f /etc/nginx/sites-enabled/default          # removes the symlink only
   nginx -T | grep -E 'listen|server_name'         # verify: only your 443 vhost
   nginx -t && systemctl start nginx
   ```

   Use `nginx -T` (capital T) to hunt a stray `listen 80`: it dumps the
   fully-merged config with every `include` and symlink resolved. Plain
   `grep -r listen /etc/nginx/sites-enabled/` misses them — `grep -r` doesn't
   follow the symlinks that fill `sites-enabled/`.

   Users then reach the sandbox at `https://sandbox.YOURDOMAIN` explicitly; plain
   `http://` on port 80 still hits the other service.

#### Both cases — firewall + renewal

```bash
ufw allow 4100/tcp             # telnet
ufw allow 443/tcp              # Case B: if ufw is active and 443 isn't open
```

**Cert renewal:** Case A's `certbot --nginx` auto-renews. Case B's *manual* DNS
challenge does **not** (no auto-DNS plugin for the registrar) — re-run the
`certbot certonly` command and refresh the TXT record before the 90-day cert
expires. Set a reminder.

---

## Updating a live droplet

Steps 0–8 are a first install. Once the service is running, a code update is
this, as `contrib_sandbox`:

```bash
cd ~/sandbox/evennia-contribs-staging
git pull
```

`server/conf/secret_settings.py` is gitignored, so the real hostname survives
a pull untouched.

Then `sudo systemctl restart evennia-sandbox`, plus whatever the pull actually
touched:

| What changed | What it needs first |
|---|---|
| Commands, typeclasses, anything under `world/` | Nothing — the restart is enough |
| A contrib's `models.py` (a new migration) | `evennia migrate` |
| A contrib's `pyproject.toml` (a new dependency) | `pip install -e contribs/<group>/<name>` |

Restart rather than `evennia reload`, and the distinction is worth knowing
because it is not the one people expect. Reload does start a *fresh* Server
process, so Server-side settings are re-read — but the Portal is left running
with the copy it loaded at boot, so anything the Portal owns (the telnet and
webserver ports, `WEBSOCKET_CLIENT_URL`, SSL) keeps the old value. Under
systemd the service's own `restart` cycles both, so it is never the wrong
answer.

Seed content last, from **inside the game** rather than the shell:

```
+sandbox/reset
```

The in-game reset runs `seed_sandbox` in the Server's own process. The shell
form (`evennia seed_sandbox`) opens a second connection to the same SQLite
file while the server holds it, which can block on a write lock — and the
running server would keep serving cached typeclass instances for rooms the
other process just deleted. Neither problem exists in-process. Use the shell
form only when the service is stopped.

A reset that follows a `START_LOCATION` change will move players: characters
standing in a purged room are sent to `DEFAULT_HOME`, which is the room the
seeder re-dresses into the Plaza. That is the intended landing, not a bug.

Confirm with `sudo systemctl status evennia-sandbox` (want `active (running)`)
and by reconnecting; `journalctl -u evennia-sandbox -n 40` if not.

---

## Troubleshooting (hard-won)

Symptoms we actually hit deploying this, most in the "two Evennia games, one
droplet" configuration:

| Symptom | Cause & fix |
|---|---|
| `apt`: "Unable to locate package python3.12" on Ubuntu 20.04, even with deadsnakes added | deadsnakes won't serve it (only the `InRelease`, no `Packages`, downloads); build with **pyenv** instead (step 1). |
| pip: "Defaulting to user installation … not writeable"; then `evennia>=6.0` "no matching distribution found" | venv **not activated** → pip used the too-old system Python. `source …/venv/bin/activate`; verify `python --version`. |
| `pyenv install` hangs at `Installing...` for minutes | Normal — it's compiling silently. `tail -f /tmp/python-build.*.log` to watch; check `free -h` for OOM on small boxes. |
| systemd: `Portal process error: No such file or directory: 'twistd'` | venv bin not on systemd's PATH → add `Environment=PATH=…/venv/bin:…` to the unit (step 7). |
| systemd stuck at `activating (start)`, Tasks: 1, no ports listening | Same PATH issue, or the manual migrate/first-boot/superuser (step 4) was skipped. |
| `nginx` won't start / `bind() to 0.0.0.0:80 failed (Address already in use)` | A default vhost with `listen 80` collides with the other game; one bad `listen` aborts all of nginx. Find it with `nginx -T`, disable it (step 8B). |
| Web client returns **Bad Request (400)** | Request host not in `ALLOWED_HOSTS` → set the real `SANDBOX_HOSTNAME` in `secret_settings.py` and restart (step 4). Means nginx *is* proxying correctly. |
| Web-admin / login returns **Forbidden (403) CSRF verification failed** | TLS terminates at nginx but Django sees plain HTTP → Origin scheme mismatch. Need `SECURE_PROXY_SSL_HEADER` + `CSRF_TRUSTED_ORIGINS` (steps 4/settings) **and** nginx sending `proxy_set_header X-Forwarded-Proto $scheme;` (step 8). Reload the login page fresh (or clear the site's cookies) after fixing. |
| Boot fails: `IndentationError: unexpected indent` in `secret_settings.py` | Stray leading whitespace; every line must be flush-left. `sed -i 's/^[[:space:]]*//' server/conf/secret_settings.py`. |
| DNS TXT / A record "not resolving" | Query a public resolver (`dig +short … @8.8.8.8`) to skip negative caching; check the record **name** wasn't double-suffixed with the domain; allow for slow propagation. |
| Web client loads but won't connect | Websocket — confirm `WEBSOCKET_CLIENT_URL` = `wss://…/ws` and the nginx `/ws` → `4102` proxy block. |

---

## Resetting

Three mechanisms, for three different needs:

- **`+sandbox/reset`** (in-game, `perm(Admin)`) — runs `seed_sandbox`
  in-process, so no restart and nobody is disconnected. Reports how many
  rooms were made by hand and therefore survive the purge; anyone standing in
  a purged room is sent home to the Arrival Hall. This is the one to use
  during a playtest.
- **`evennia seed_sandbox`** — content-only. Purges and rebuilds the default
  rooms/exits/board/calendar-event/lore/plot content plus the region, the map
  plane and its tiles, and the two scenes that light the tile overlays
  (tagged/name-matched, so reruns don't duplicate). Keeps accounts and
  characters.
- **`scripts/reset_to_golden.sh`** — see step 6. Full wipe when
  revived. Stops the server, swaps in
  the committed `server/evennia_default.db3`, restarts. Wipes accounts too.
  Re-snapshot the golden file after every `evennia migrate` (see step 6).

---

## Verification checklist

1. **Coexistence** — the other game's telnet/web still respond; no port
   collision.
2. **Reachability** — `https://sandbox.YOURDOMAIN/` (webclient) and
   `telnet sandbox.YOURDOMAIN 4100` both connect.
3. **Every contrib runs** — walk the OOC wing and run what each plaque
   names. Eight rooms, hub-and-spoke off the Arrival Hall, covering all ~42
   commands: Posing Studio, Scene Room, Social Commons, Story Office, Lore
   Archive, Help Desk, Drafting Room. No import/lock/settings errors.
4. **A new account lands in the world** — register a fresh account (not
   Account #1, which is a superuser and bypasses every lock) and confirm it
   spawns in the Arrival Hall rather than stock Limbo, and that `+ooc` from
   one of the spokes brings it back there. This is the whole
   `START_LOCATION`/`DEFAULT_HOME`/`OOC_ROOM_DBREF` arrangement, end to end.
5. **The Builder toggle flips both halves** — as that fresh account, run
   `help` and note that `+jobs`, `+discuss` and `+rptracker` are absent; run
   `+sandbox/builder on` and confirm all three appear and that
   `+map/place`/`+region/create` stop refusing; then **from the Drafting
   Room** run `@dig north=A New Room` and confirm the map grew on its own,
   and `@dig gate=Another Room` and confirm it did not. The Drafting Room is
   where this works because it is the one OOC room holding a tile — the
   auto-placement listener only fires from an already-mapped source, so the
   same commands typed in any other wing room do nothing at all, silently.
   Confirm the new rooms landed on `Sandbox Scratch`, not on the IC plane.
   `+sandbox/builder off` puts it all back.
6. **Seams fire** — pose in a seeded room; the pose fires evennia_posing's
   `pose_recorded` signal, which the listener in `world/sandbox/glue.py`
   fans out to `capture_to_scene` and `record_rp_activity` — confirm with
   `+activity` (shows a tracked RP session) and `+scene` after `+scene/open`
   (shows the auto-captured pose).
7. **Seeder is idempotent** — run `evennia seed_sandbox` twice; no
   duplicate rooms/boards/entries.
8. **In-game reset works** — after step 5 dug a room or two, run
   `+sandbox/reset` as staff: the seeded world comes back, your account and
   character survive, and the reported count of hand-made rooms matches what
   you dug. Then confirm the rooms you dug are **still reachable from the
   Drafting Room** and still hold their scratch-plane tiles — that room and
   the scratch plane are both exempt from the purge precisely so the reset
   cannot orphan what a playtester built.
9. **Golden reset works** — in a disposable game copy, restore
   `server/evennia_default.db3` as `server/evennia.db3`, then run
   `evennia migrate --noinput` and `evennia seed_sandbox`. Reseeding refreshes
   dated fixtures so the demo challenges don't expire from time spent in Git.
   The Proving Grounds should contain both
   demo sheets, the dummy and two open challenges. A deployed full wipe
   uses `scripts/reset_to_golden.sh`; keep the generated admin credential
   from step 6 in your password manager.
10. **The map renders, in a browser** — `/map/` lists four planes:
    `Sandbox Overworld`, `Sandbox Undercroft`, `Consulate Interior` and
    `Sandbox Scratch`. `/map/<pk>/` for the overworld draws eight tiles as an
    SVG plus grid (nine rooms, less the staff-only Warren), with the Archive
    north of the Plaza, sprites on four of them and the plain fallback swatch
    on the Causeway. The whole OOC wing is deliberately absent, and doubly so:
    its exits carry no direction aliases, and
    `MAPS_UNMAPPABLE_ROOM_TYPES = ("ooc",)` stops the auto-placer mapping those
    rooms even if somebody digs a real direction into one. `/map/<pk>/live/`
    loads Leaflet with the **base-layer control** offering Overworld and
    Undercroft — that control only appears because two planes share the
    `overworld` zstack. This is the one step no test replaces: a static SVG
    page and a client-side Leaflet render fail in different ways.
11. **Overlays light up and link out** — on the live map, toggle the overlay
    controls: the Consulate Hall shows an active-scene pin and an upcoming
    event, the Archive shows the heaviest heat (three closed scenes against
    Market Row's one) and recent logs, three rooms show different hangout
    letters, and tiles are labelled `The Commons` *or* `The Waterfront` rather
    than all the same. Click through a tile popup to the region, the scene log
    and the event page. Then click the **portal marker** on Consulate Hall and
    confirm it navigates to the `Consulate Interior` plane.
12. **Staff-room privacy and public lottery mode** — as the fresh account
    from step 4, confirm the Warren is absent from the map, from `/regions/`
    and from `+where`. Market Row still shows the Staff Briefing event for
    players and staff: `is_staff_event` selects lottery RSVP mode rather than
    hiding the event. Run `+sandbox/builder on` and confirm only the Warren
    changes with the staff toggle.
13. **`+map/check` and `+map/reflow` have something to report** — as staff, run
    `+map/check`: it should name the Study as an unmapped neighbour of the
    Lobby, the Warren as a blank-terrain tile, and the Drafting Room as a tile
    on an off-map room type. Then run `+map/reflow` from the Cistern as a dry
    run and confirm the two-step cascade: Service Tunnel `blocked_by_pinned`,
    Vault `blocked_by_blocked`. Do **not** apply it — the misalignment is the
    demo.
14. **A missing partner degrades, it does not break** — `pip uninstall
    evennia-calendar`, drop it from `INSTALLED_APPS` and from
    `web/website/urls.py`, restart, and confirm the map still renders with the
    events overlay simply absent. This is the whole point of the signal gating
    and no unit test covers it, because a test process cannot uninstall an
    app. Reinstall afterwards.
15. **The web UI stays navigable** — render `/`, `/help/`, `/channels/`, and
    the account's `/characters/` and `/characters/manage/` pages. Confirm
    Help search keeps literal command names, non-Builders cannot see restricted
    categories, MudInfo is absent from Channels, and pagination appears only
    when a list has another page. Open `/api/v1/` and `/webclient/`; verify the
    API root renders, the client has a route back to the site, and its reading
    pane is narrower than the viewport.
16. **The contrib shell stays self-contained** — open a list and detail page
    for each mounted web contrib and inspect the rendered source: its page
    links the contrib stylesheet, tables sit in a focusable scroll region, and
    empty collections explain what belongs there. Resize the browser to a
    narrow viewport and confirm data tables become labelled stacked rows at
    640px or below, with readable titles and working links. The calendar opens
    as a chronological list of the selected month; its explicit Month Grid,
    List View, and Automatic controls work with JavaScript disabled. An explicit
    mobile grid scrolls inside its own region.
17. **Phase 4 relationships and identifiers** - open a region and follow a
    member room, then follow its map placement; open a scene and verify its
    public number, room, participants, and related lore/plot/event links. Use
    `+scene/info <scene_number>` and `+log <scene_number>` in-game, confirming
    the displayed public number is the argument accepted by both commands.
    Confirm a standalone event explains `+rsvp` and a clustered event links to
    the ranked RSVP page. Check that only secondary region memberships carry
    a badge and that long board titles leave the byline and actions readable.
    In the webclient, confirm room headings show names without dbrefs,
    including when logged in as a builder.


### Present activity on the web

The home page and both map views link running scenes to readable logs. The
**Happening Now** menu opens `/scenes/live/`; `/scenes/` remains the archive.
Live logs begin on the newest page, show participants, and poll every ten seconds.
Numbered earlier pages stay put, OOC filtering survives pagination, and manual
refresh works without JavaScript. The poll uses the same privacy checks as the
initial page; view-private scenes still require an invitation or staff access.

Boards show the latest post and author plus unread counts for the signed-in
account. Reading a full board marks the displayed posts read independently of
subscription login notifications. Characters show online state, last seen, and
their `+finger/set role` concept. Last seen records character puppet/unpuppet
activity, so a web login alone does not make a character look active. Existing
characters show **Not recorded** until they next connect; demo speakers have
different concepts but are not presented as connected players.

The seed varies scene lengths and speakers, with an intentionally empty archive
entry, plausible timestamps, authored/tagged lore, and posts on both boards.

Browser check: open a live scene from the home page and map, add a pose in-game,
and confirm it arrives within ten seconds. Check the latest-page rollover, an
earlier numbered page, and Show OOC. Close the scene and confirm polling stops.
Change a scene to view-private while an uninvited reader follows it and confirm
the reading area clears. Read a board, return to the index, and confirm its
unread count clears only for that account. Disable JavaScript and verify the
manual refresh link. Check the character list after connecting/disconnecting.

Mobile verification: run `python scripts/ui_shots.py --viewport mobile` from the
repo root against the running sandbox. The report records page/viewport widths
and the script fails for horizontal page overflow, non-200 responses, or browser
warnings/errors. Check both populated and empty tables and the calendar's month
navigation. Desktop tables keep their columns. After a reseed changes IDs, use
`--routes-file <file.json>` with an explicit JSON list of `["slug", "/path/"]`
pairs; this also allows extra routes such as history and staff pages.

### Live RP playtests

From the repository root, using the Python 3.12 environment with Evennia
6.0.0 and all contribs installed editable in the dependency order above:

```sh
python -m pip install psutil==7.1.0 playwright==1.62.0
python -m playwright install chromium
python scripts/test_playtest.py
python scripts/playtest.py run --suite rp
python scripts/test_playtest_interactive.py
```

The default runs a fresh deterministic Telnet RP suite plus Chromium, then a
separate fresh host with normal RNG. Each host copies the scaffold into
`.playtest-runs/<run-id>/game/`, creates a new database, seeds inside Evennia's
initial setup and waits for its first restart. Five distinct ports bind only
to `127.0.0.1`. Existing sandbox accounts, database, secrets and processes are
never reused. Password hashing and login throttling keep their normal settings.
The owner account only bootstraps the database; gameplay uses ordinary players
and a nonsuperuser Builder.

The RP pass covers draft validation and finalization, pip policy,
allowance/XP transactions and refunds, loadouts, scene and tracker integration,
private ratings, challenge binding/alternatives/retries, once/edit/void
authorization, literal comments and reconnect persistence. A per-check
`ScriptedRoller([10])` makes B++ Presence with Performance Proficiency against A
resolve to Narrow Success. The normal profile checks real outcome records
without assuming a particular roll. Chromium uses anonymous `/webclient/`
pages in independent contexts, types real password logins into the input
widget, checks a sheet and RP result, verifies the public scene log and captures
desktop/narrow screenshots. Browser traces and video are disabled.

`--profile deterministic`, `--profile normal` and `--no-browser` are partial
passes, recorded as such. Timeouts are configurable with `--startup-timeout`
(180 seconds), `--action-timeout` (15), `--browser-timeout` (30) and
`--shutdown-timeout` (30). Exit codes: 0 means the selected nonempty suite
passed, 1 means a scenario or server-log assertion failed, 2 means setup,
protocol or cleanup failed. Inspect `evidence/results.md` for case results.
CI runs the complete pass twice on Ubuntu after the sandbox integration gate.

For exploration, keep one runner process alive:

```sh
python scripts/playtest.py interactive
```

It defaults to normal RNG. Read the initial `{"event":"ready",...}` message,
then write one JSON object per stdin line. The host, actors and sockets persist
between requests. Responses echo the request `id`; unsolicited transcript
events carry monotonically increasing `seq` values. Diagnostics go to stderr.
These requests can be sent interactively or from an agent/process driver:

```jsonl
{"id":1,"op":"send","actor":"alice","command":"look"}
{"id":2,"op":"send","actor":"bob","command":"ooc Ready to test."}
{"id":3,"op":"read","actor":"alice","after":0}
{"id":4,"op":"expect","actor":"alice","pattern":"Ready to test","after":0,"timeout":5}
{"id":5,"op":"snapshot"}
{"id":6,"op":"disconnect","actor":"bob"}
{"id":7,"op":"send","actor":"bob","command":"+sheet"}
{"id":8,"op":"quit"}
```

Actors are `alice`, `bob`, `staff`, `browser` and `browser-observer`. Each first
use logs in normally; `send` accepts exactly one command line. `read` returns
sanitized raw and ANSI-normalized receive/send records after a sequence cursor;
`expect` matches normalized received text after that cursor. `snapshot` uses
the Builder's fixed, read-only projection of enrolled characters, transactions,
checks, challenges, scenes and tracker sessions. It accepts no arbitrary query
or Python. JSONL errors are responses with `ok:false`; EOF and `quit` shut down
the owned host. An interactive session is exploration, not a suite pass.

Synchronization hooks exist only in the disposable copy. They require a matching
run marker, localhost configuration and an enrolled account; state inspection
also requires the designated staff role and Builder permission. Gameplay still
passes through Evennia's normal authenticated command dispatcher. A nonce
boundary means **dispatch returned**: progressive menus and delayed work may
continue, so use `expect` for their visible prompts. Scripted RP commands are
non-progressive. Do not install these hooks in a persistent game.

Only `.playtest-runs/<run-id>/evidence/` is suitable for sharing. It contains a
sanitized manifest, sequenced actor transcripts, snapshots, results, logs and
browser diagnostics/screenshots. The sibling `game/` contains disposable
passwords, settings and the full database; CI uploads only `evidence/`.
Run directories are retained for diagnosis. Shutdown first requests Evennia's
normal stop, then verifies the PID's creation identity and the exact run directory before
terminating any remaining owned processes. No existing game can be targeted by
the CLI. A source-project adapter is future work.

On Linux, identity uses `/proc`'s boot-relative start counter so WSL/NTP clock
adjustments cannot hide an owned process. `evidence/cleanup.json` records the
verified shutdown.
