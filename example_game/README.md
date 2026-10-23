# example_game — Contrib Sandbox

A persistent, hand-tested downstream Evennia 6.0 game that installs and wires
together every contrib in this repo. It exists for two reasons:

1. **Reference integration.** It's the "how do these contribs actually get
   wired into a real game" example this repo otherwise lacks — settings,
   cmdsets, server hooks, and the typeclass seams that can't auto-wire.
2. **A living sandbox to hand-test against**, as contribs and their integrations
   grow.

Full design background is tracked separately (local-only planning docs, not
part of this repo).

---

## What's wired up

All current contribs, in dependency order — `evennia_links` first, then
`evennia_economy` and `evennia_rp_resources`, followed by `evennia_rp_crafting`.
Other apps that depend on links include `evennia_rptracker`, `evennia_scenes`,
`evennia_boards`, `evennia_lore`, `evennia_plots`, `evennia_regions`,
`evennia_maps`; then come the standalone apps (`evennia_calendar`,
`evennia_jobs`, `evennia_xp`, `evennia_accessibility`, `evennia_guides`), then
the pose/social layer (`evennia_posing` before `evennia_social` — social hard-depends on
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
| `LORE_SESSION_CONTEXT_PROVIDER` | `evennia_lore.integrations.session_context.get_session_context` → room, primary region, plots |
| `LORE_STAFF_REVIEW_HOOK` | the same jobs reporter → lore affirmation requests, and sealed lore left on a thread a player concluded |
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

### NPCs

`evennia-npcs` 0.1 is installed after links and rp-rules, independently of combat.
`typeclasses/npcs.py` puts `NPCCharacterMixin` before the sandbox `Character`;
its safeguards and NPC-only command set take precedence over PC login rewards
and build/economy commands. `NPCCmdSet` is registered last on player characters
so virtual portrayal overrides pose/say/emit/semipose and `+test` coherently.
NPCs use their own scene-capture signal and are excluded from RPTracker rewards.

`seed_sandbox` adds a Market Porter template and a Visiting Envoy unique NPC in
the market. Try `+npc`, `+npc/spawn Market Porter`, then `+npc/puppet #object-id`,
`pose offers directions.`, `+test presence`, `+npc/unpuppet` and
`+npc/despawn #object-id`. Sharing and requests use `+npc/permit` and `/request`.
Scene appearances survive despawn and history rechecks current scene privacy.
Optional plot links share the creative-content checklist point with IC posts.

The sandbox enables NPCs and opt-in full puppeting for demonstration. Production
hosts default to dark rollout and virtual portrayal. `NPCS_REVEALED`,
`NPCS_FROZEN` and `NPCS_COMBAT_PROFILES_REVEALED` are runtime switches. Combat
profiles ship dark; no combat action engine is present. The server startup hook
ensures one cleanup Script is running. See the
[NPC install guide](../contribs/game_systems/evennia_npcs/README.md) for host policy.

### Economy, stalls and resource gathering

`evennia-economy` 0.2 adds market stalls as well as integer purses and passive weekly income with a
five-UBI-week base cap, once-only starting stipends (plus a reveal stipend
when a hidden economy is revealed), and atomic exchanges
of money, carried items and resource counters. Demo authors start with 200 coins.
Use `+balance`, `+offer character=5 coins for resource:grain:2`, and `+accept number`;
`/secret` on either offer or acceptance suppresses the room announcement. Stock
`give` is replaced so gifts enforce the same-account rule too; it stays available
while the economy is hidden (items only) and for item gifts while frozen.

Staff use `+economy` for reconciliation and per-account accrual, `/run dry` for
income previews, `/credit` and `/debit` for adjustments, and `/flags` for review.
The generic jobs reporter files cross-asset round-trip flags as staff discussions.
Runtime settings control reveal, freeze, stipend amounts, income, taper, cap weeks,
offer limits and zero-default fees. The server-start hook ensures the scheduler
runs; the character login hook quietly summarizes income once. No economy mixin,
MRO change or web/API mount is needed. Stalls are a later milestone.

`world/sandbox/test_economy.py` exercises actual resources, worn equipment,
review jobs, commands and login/start hooks. CI verifies truly absent resources,
jobs and equipment in fresh environments; resources also runs without economy.
The live suite trades resources and money between ordinary sessions, checks
same-account refusal, secret acceptance, freeze/reveal and reconnect persistence.

Market Row is tagged as a market with eight slots and a stocked demonstration
stall. Try `look`, `+browse`, `+buy <listing number>` and `+market satchel`.
`+stall/claim`, `/name`, `/desc`, `/list`, `/unlist` and `/close` manage your own
counter. Items and resource lots are reserved, so a buyer can purchase while
the seller is offline. A held stall raises the money cap by 100 coins; closure
returns remaining stock and removes that raise. Five quiet weeks create a staff
review job without closing the stall. Same-account `drop`/`get` handoffs also
create review flags without blocking pickup. The room's `MarketRoomMixin` comes
before the host room class and cooperatively adds the roster; the login hook
calls `stalls.note_login`. These hooks are gated in absent-partner profiles.

`evennia-rp-resources` 0.1.3 is wired with a generic Materials / Provisions /
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
social and login seams. Fresh CI profiles exclude maps, plots, social, tracker
or economy and verify the excluded package cannot be imported.

The **Supply Court** off the market holds **Sample Supply Shop**, with a timber
lot available through `+browse` and `+buy`. `The Supply Expedition` demonstrates
a staff-approved rare-crystal payout budget. Eligible active participants
receive rewards when the Plot concludes. Owners propose with
`+resources/payout #<plot>=quantity resource`; staff use `/payoutapprove` and
`/payoutretry` for authorization and recovery.

The market also has a system seller, switched off by default. Staff may enable
`RP_ECONOMY_SYSTEM_SELLER` through `+runtime`, then use `+browse/system` and
`+buy/system timber=2`. Base prices are in `RP_ECONOMY_BASIC_PRICES`.
The host registers `CmdShop` and calls the resource award login helper. No additional MRO,
URL or API mounting is needed. Building's rendered transfer form includes an
explicit return-or-transfer choice for shop merchandise.

### Workshops and crafting

`evennia-rp-crafting` seeds Weaver, Jeweller, Smith, Scribe, Cook and
Illusionist niches.
At Market Row, a sample field book can be read and a woven cloak shows a
verified maker hallmark. The demonstration crafter owns a Workshop; resetting
rebuilds demo stock while preserving player Workshops and craft history.
The sample travel book demonstrates two titled pages:
`read/contents a sample travel book`, `read a sample travel book=2`, then
`read a sample travel book` to resume that character's bookmark. Create pages
with repeated `+craft/page title = text`; each extra page costs one additional
material by default. The shared pagination helper comes from Links 0.8.7.
The sample field journal has three prepaid pages and one attributed entry;
the sample journal edition freezes that entry. Pick up the journal, then try
`+journal/write a sample field journal = I stopped by the well.`
Use `/revise` and `/history` to see preserved revisions. Gifting or selling
the journal lets its new holder append entries while keeping earlier writers'
attribution. Create your own with `+craft/journal 3` in a Readable draft.
`+craft/copy a sample field journal = writing/a journal edition` starts a
copy draft: preview it with `+craft`, select resources and `/finish` at normal
crafting cost. Source revisions never change completed editions.
The old market chronicle is a staff tome, readable without crafting. Its second
page cites lore: `read an old market chronicle=2` acquires that entry; contents
and the first page do not. The sample annotated guide carries the same citation
and a recognition feature that appears after learning it. Crafters can attach
references with `+lorecraft/cite [page] = #entry` and
`+lorecraft/recognise #entry[/<niche>]=<feature text>` before previewing and finishing
their draft. Staff can publish independent tomes through `+tome`; the host's
`StaffTome` keeps the stock-deletion guard before the reusable `LoreTome` in
its MRO. Journals and citation-preserving editions need their separate bridge.
The market also holds a sample spice cake and spark globe. Pick one up and
`use <item>` emits its EVENT and consumes it. Compose your own through
`+craft/new cooking/consumable`, `/desc`, repeated `/beat`, `/resources`, preview
and `/finish`. Broadcast uses `illusions/broadcast` with essence inputs.
`+ambient/mute` suppresses effects arriving from another room; your current
scene remains visible. Broadcasts reach adjacent rooms only, never channels.
Persistent audience limits default to 30 seconds and survive server reloads.
Crafted EVENTs respect Social ignore through their user/current owner. Scenes
0.8.2 records one attributed entry per affected room, including adjacent
Broadcast rooms, without starting scenes or adding participation/pose counts.
They leave pose order and RP activity unchanged; owner-written `+pet/pose`
continues through the ordinary owner posing path. The actual-partner assertions
live in `world.sandbox.test_emissions` and the wave-two/three seam suites.

Use `+workshop/catalog` for current unlock costs, then
`+workshop/unlock writing = 3 timber`, then `+workshop/unlock writing`
and the printed token confirmation. A second active niche costs twice its
base inputs, then three times for a third. The five-niche cap is mandatory
and runtime-tunable. `+workshop/abandon writing` frees the slot without a
refund and lowers the money/resource cap raise.

Compose with `+craft/new writing/readable = a field book`, `/desc`,
`/text`, `/resources 1 timber`, preview with `+craft`, then `/finish`.
Wearable drafts use `/line`, optional `/aura`, `/slot` and `/require`.
Crafted wearables reuse equipment's requirements and sealing and do not use
the plain-gear cap. Staff `+crafting/review` sees the original prose and costs.

Books now have the Carried lifecycle and a Readable verb; the commands and price
stay the same. `RP_CRAFTING_COMBINATIONS` explicitly lists complete verb sets
and leaves only the original products open. The foundation supports composed
items when a host deliberately enables and tests a combination, with every
contributing niche required and each component paid once. Staff review and
market keywords include all contributors. Activation, installation and the
remaining item facets are separate follow-ups.

The host's crafted item typeclasses put `ObjectParent`
first, so economy's early stock-deletion guard runs before item cleanup.
Crafting's hallmark mixin precedes equipment/DefaultObject through the contrib
base classes. No crafting character mixin, startup script, URL or API is needed.
Without equipment, existing crafted objects retain their hallmark and new
Wearable crafts are unavailable; Readable continues to work. Without economy,
unlock costs use resources only. Without accessibility, Broadcast remains in
its user's room. CI tests actual physically absent partners
through `scripts/ci_run_crafting_tests.py`.

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

**Eight tile overlays, zero overlay settings.** `evennia_maps` knows where
rooms are and nothing else. Once per map render it sends `collect_tile_overlays`.
Five contribs each answer for the rooms they know about, from providers they
connect themselves in their own `AppConfig.ready()`:
- `evennia_regions`: `primary_region`;
- `evennia_scenes`: `has_active_scene`, `active_scenes`, `recent_scene_count`
  and `recent_scenes`;
- `evennia_lore`: `has_lore`;
- `evennia_calendar`: `upcoming_events`;
- `evennia_social`: `present`, who's here.

Nothing in `settings.py` configures this. Uninstall a partner and its layer is
simply absent. `world/sandbox/tests.py` (`TestMapOverlaySeam`) is the
end-to-end proof, and it can only live here: no contrib's own suite installs
the others.

Who's here shows only on the live map, which requires a login: "N here" in the
tooltip and room list, and the names in the room panel. It honors `+unfindable`.
Players don't see unfindable or dark characters there unless their own
connected character is in the same room; staff see them with a marker. Browser
check: connect two characters to one room, set one `+unfindable`, and compare
the live map as a player in that room, a player elsewhere, and staff.

Clicking a tile opens its **room panel**: beside the map on a wide screen, a
bottom sheet on a phone. Market Row shows every section the sandbox has: lore
tied to the Commons (what your character knows, linked, and the rest locked),
The Founding Storm through its market-day scene, and the scrap its urban terrain
yields. `world/sandbox/test_map_panel.py` checks each section from the real
partners, including that learning an entry unlocks it and that gathering waits
for `RP_RESOURCES_REVEALED`.

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

### Retheming the contribs' pages

The sandbox deliberately has no theme, so you see each contrib's own pages. Every
colour in their stylesheets is a shared `--evennia-color-*` token with its usual
colour as the fallback, and `web/static/website/css/custom.css` reads the same
tokens. A game sets them on `:root` in its own stylesheet to retheme every
contrib page at once. The token list is in evennia-accessibility's README, and
`scripts/check_templates.py` rejects a contrib stylesheet colour that isn't a token.

To see it, add this to `custom.css`, run `evennia collectstatic --noinput`, and
reload a board, a lore diff, the calendar and the job form:

```css
:root {
  --evennia-color-muted: #8a3b12;
  --evennia-color-border: #8a3b12;
  --evennia-color-surface-alt: #fbeee0;
  --evennia-color-success-bg: #fff3c4;
}
```

Empty states and table borders turn rust-coloured, past calendar days turn
cream, and today and added diff lines turn yellow. The rule above each form's
buttons follows too, through accessibility's own tokens. Remove the block to
undo it.

### Which character the website acts as

A visitor doesn't need to be connected in-game to act as their character on the
site. Every web contrib resolves the character through
`evennia_links.characters.web_character`. An account with several characters
picks one from the account menu, which uses Evennia's own puppet link. The
menu then reads "Playing as *Name*", and every page and write follows that
choice. `evennia_links.web.WebCharacterMiddleware` (the `####`-bannered block in
`settings.py`) passes the choice to the contribs, and the
`web_character_context` processor gives `_menu.html` the same character. Every
authoring form says "Posting as **Name**" above its submit button.
`world/sandbox/test_web_character.py` is the seam test: it picks a character
through the real link, then checks the menu, three contribs' forms and a real
job write.

Browser check: with two characters on one account, pick each in turn from the
account menu. Confirm that the menu, a board post form and the job form all
name the same character, and that a filed job lists it as the author.

### The guide

`/guide/` serves the Markdown pages in `world/guides/`, along with the pages
the installed contribs ship: player pages for each system (`checks`,
`character-sheet`, `signature-moves`, `tests`, `posing`, `scenes`, `social`,
`rp-sessions`, `xp`, `lore`, `plots`, `calendar`, `map`, `regions`, `boards`,
`requests`, `accessibility`, `npcs`, `building`, `building-frontier`, `combat`,
`combat-moves`, `combat-storytelling`, `party`, `party-surge`,
`party-boss-checks`, `equipment`, `joining`, `economy`, `resources`, `crafting`,
`crafting-letters`, `crafting-fixtures`, `companions`, `crafting-modifiers`,
`patterns`), a few principles and glossary
terms, and staff pages: guides' own `writing-guides` and the contribs'
`<contrib>-staff` pages: `equipment-staff`, `moderation-staff`, `jobs-staff`,
`social-staff`, `rptracker-staff`, `plots-staff`, `lore-staff`, `scenes-staff`,
`calendar-staff`, `boards-staff`, `xp-staff`, `building-staff`, `maps-staff`,
`regions-staff`, `npcs-staff`, `links-staff`, `chargen-staff`, `contest-staff`,
`combat-staff`, `party-staff`, `economy-staff`, `resources-staff` and
`crafting-staff`. A page here with the same
key as a contrib's page replaces it.

The navbar's **Guide** dropdown links Start here, the full index, the design
principles and the glossary. Staff also get **Staff guides**, which opens
`staff-start-here`: an index of the staff tools by task. The home page links
Start here, and the systems table links each contrib's player page when players
can see it. `start-here` links every system page by what a player wants to do.
`GUIDES_STAFF_LOCK` is `perm(Builder)`, matching the staff commands, so anyone
who can run a staff command can read the staff pages. In this sandbox,
`+sandbox/builder on` grants that. `economy` requires `RP_ECONOMY_REVEALED`, which is a runtime setting:
turn it off with `+runtime RP_ECONOMY_REVEALED=false` and the page, and the
links to it, disappear without a reload. Every page's "Ask about this page"
opens the jobs request form, prefilled. The guide is web-only and separate from in-game `help`. Run
`evennia guides_check` after editing pages. `world/sandbox/test_guides.py` is
the seam test. It renders every system page through the site, and checks that
each contrib's pages link only to pages its required dependencies ship, so they
still validate in a game without the optional partners.

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
| Story Office | `-plots`, `-calendar` | `+plot`, `+thread`, `+arc`, `+hook`, `+calendar`, `+cluster`, `+rsvp` |
| Lore Archive | `-lore` | `+lore`, `+investigate`, `+hint`, `+share`, `+forget` |
| Help Desk | `-jobs`, `-boards`, `-xp` | `+bb`, `+jobs`, `+request`, `+bug`, `+issue`, `+discuss`, `+xp` |
| Drafting Room | `-maps`, `-regions` | `+map`, `+region`, `@dig`, `@tunnel` |
| Proving Grounds | `-rp-rules`, `-rp-chargen`, `-rp-equipment`, `-rp-contest` | `+sheet`, `+stats`, `+pips`, `+abilities`, `+spend`, `+upgrade`, `+lock`, `+unlock`, `+test`, `+chargen`, `+gear`, `+wear`, `+remove`, `+worn`, `+outfit` |

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
+spend/ability Proficiency/Athletics
+upgrade Proficiency/Athletics
+sheet
+test/list
+test #2=Agility/Athletics~I leap across.
```

Domains suggest an approach in their descriptions; any stat/tag pairing is
legal. The second tag kind is fighting styles: Blades, Blunt, Polearms,
Archery, Unarmed and Spellcraft. A move would have a style, and any test may
carry one. The seeded Storyteller has Proficiency/Performance, the Visitor has
Combat Focus/Blades, and both have finalized sheets and a flaw. Builder mode lets you
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
playtesting, run `+sandbox/builder on`, then `+xp/grant <character>=10 # Playtest`.
`+spend` shows both balances. Staff can revoke with an exact refund using
`+chargen/refund <character>=<ability>/<tag>`.

**Practice gear.** Equipment grants nothing; it asks a build to commit. The
Proving Grounds floor holds a travelling cloak that asks for nothing and a
heavy maul that asks for Strength `++`. The Storyteller wears duelist's gloves
(Agility `++`) and the Visitor a blade charm (Combat Focus/Blades equipped),
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

`RP_EQUIPMENT_REVEALED` is on here. `+runtime RP_EQUIPMENT_REVEALED=false`
hides the gear commands and the `equipment` guide page from players without a
reload; staff keep both, and worn gear stays worn.

The Character typeclass calls the contrib's display helpers rather than mixing
in `EquipmentCharacterMixin`, because equipment requires chargen and is absent
whenever chargen is.

Equipment also supplies free outfits and slot covering for plain and crafted
gear. The sandbox configures `cloak` to cover `body`. The first demonstration
character wears a practice tunic beneath an overcloak: ordinary `look` and
`+worn` show the cloak, while `+worn/all <character>` includes the tunic.
Remove the overcloak to reveal it. Each demonstration character has a saved
`Practice` outfit, including hidden gear. For your own gear, use:

```text
+outfit/save Travel
+outfit/show Travel
+outfit Travel
+outfit/delete Travel
```

Applying a set replaces everything worn and refuses the whole change if an
item is missing, a requirement is unmet or your build is locked. Covered gear
continues to hold its requirements. `world/sandbox/test_rp_partners.py` checks
seeded layers and optional equipment absence; `test_crafting.py` checks a set
mixing a sealed crafted cloak with a plain shirt without changing provenance.

Every name above belongs to the game, not the contribs. Stats, domains, styles
and abilities are named in `world/ruleset.py`. The sheet's nouns (pips,
weakness, loadout, points) are set in the RP block of `server/conf/settings.py`,
and their contrib defaults are listed there. To rename a command such as
`+pips`, follow "Renaming things for your game" in the
[rp-chargen README](../contribs/rpg/evennia_rp_chargen/README.md#renaming-things-for-your-game).

The CI `sandbox` job runs the full sandbox gate with all partners, and the
`rp-sandbox` job runs fresh environments with scenes, tracker, XP, chargen, equipment or contest
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

### Structured staff requests

Jobs 0.4 adds matching web and in-game questionnaires. Open **My Tickets** and
choose **Propose a build**, or use `+request/forms` then
`+request/form build=My proposal`. Answer with `+request/answer <key>=<answer>`,
inspect `/preview`, and `/submit`. `/resume` continues an unfinished questionnaire.
Use `+request/edit <key>` for a multiline text answer in the editor.
The enabled form covers homes, shops and frontier proposals and requires an
acknowledgement that the author's content may return in a later game or storyline.
Questions and consent wording live in `world/sandbox/content.py`.

`seed_sandbox` creates one demonstration library proposal visible to staff at
`/jobs/all/`. Reseeding replaces that demonstration by its stored identity;
player requests survive even if they have the same title.
Staff can request changes, approve or decline via the ticket's **Review proposal**
link or `+jobs/approve <ticket>.<revision> # <explanation>` (also `/decline` and
`/revise`). Changes requested enable a new revision; previous answers and decisions
stay visible. Pattern and Region form examples are disabled until those workflows
are ready. This release collects and reviews proposals; room construction and
promotion arrive with building. No building partner is needed to use Jobs.

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
         contribs/game_systems/evennia_economy \
         contribs/game_systems/evennia_rp_resources \
         contribs/game_systems/evennia_rp_crafting \
         contribs/game_systems/evennia_rptracker \
         contribs/game_systems/evennia_scenes \
         contribs/game_systems/evennia_boards \
         contribs/game_systems/evennia_lore \
         contribs/game_systems/evennia_plots \
         contribs/game_systems/evennia_regions \
         contribs/game_systems/evennia_maps \
         contribs/game_systems/evennia_calendar \
         contribs/game_systems/evennia_jobs \
         contribs/game_systems/evennia_moderation \
         contribs/game_systems/evennia_xp \
         contribs/utils/evennia_accessibility \
         contribs/utils/evennia_guides \
         contribs/game_systems/evennia_posing \
         contribs/game_systems/evennia_social \
         contribs/rpg/evennia_rp_rules \
         contribs/rpg/evennia_rp_chargen \
         contribs/rpg/evennia_rp_equipment \
         contribs/rpg/evennia_rp_combat \
         contribs/rpg/evennia_rp_party \
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
         contribs/game_systems/evennia_economy \
         contribs/game_systems/evennia_rp_resources \
         contribs/game_systems/evennia_rp_crafting \
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
         contribs/utils/evennia_guides \
         contribs/game_systems/evennia_posing \
         contribs/game_systems/evennia_social \
         contribs/rpg/evennia_rp_rules \
         contribs/rpg/evennia_rp_chargen \
         contribs/rpg/evennia_rp_equipment \
         contribs/rpg/evennia_rp_combat \
         contribs/rpg/evennia_rp_party \
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

The seeded `IC RP` channel uses `evennia_rptracker.typeclasses.ICChannel`.
Puppet a character, subscribe with `channel/sub IC RP`, and send with
`channel IC RP = <message>`. Channel activity has separate session and XP sources;
it does not alter room pose timers or create scene links. Staff can inspect
rolling region and channel totals with `+report/activity [days]`.

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
    than all the same. Click a tile to open its room panel, and click through
    to the region, the scene log and the event page. Open Market Row's panel
    and check its lore, plot and gathering sections, then narrow the window
    below 768px and confirm the panel becomes a bottom sheet that Escape
    closes. Then click the **portal marker** on Consulate Hall and confirm it
    navigates to the `Consulate Interior` plane.
12. **Staff-room privacy and public lottery mode** — as the fresh account
    from step 4, confirm the Warren is absent from the map, from `/regions/`
    and from `+where`. Market Row still shows the Staff Briefing event for
    players and staff: `is_staff_event` selects lottery RSVP mode rather than
    hiding the event. Run `+sandbox/builder on` and confirm only the Warren
    changes with the staff toggle.
13. **`+map/check` and `+map/reflow` have something to report** — as staff, run
    `+map/check`: it should name the Study as an unmapped neighbour of the
    Lobby, the Warren as a blank-terrain tile, and the Drafting Room as a tile
    on an off-map room type. Then run `+map/reflow The Cistern` as a dry
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
**Events** lists **Happening Now** before **All Scenes**: the former opens
`/scenes/live/`, and the latter opens the archive at `/scenes/`. **Setting → All
Maps** opens the plane list. The homepage map widget links anonymous visitors to
the static map and authenticated accounts to the live map when its API is mounted.
Direct live-map links also redirect anonymous visitors to the static map.
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
The lore shows each layer feature: an affirmed Fact, a false Rumor whose OOC
notes say so, and a Legend with sealed notes, linked to the seeded plot.
Concluding that plot reminds whoever concludes it that the legend is still sealed.

The seeded plots show threads (evennia-plots 0.7). The Founding Storm is owned
by the first demo speaker and takes threads **by request**. It has a held
thread with a sealed answer, which makes the plot *Owner-led*, and an open
thread the second speaker leads. The second speaker also has a pending request.
Its prequel, The Quiet Before, is concluded, and its loose end has been carried
into the Storm. `world/sandbox/test_plots.py` renders these pages through the
site and checks that the sealed answer and the request stay hidden from
visitors.

Browser check: open The Founding Storm as a visitor and as its owner (puppet
the first demo speaker). Only the owner sees the request, the accept and
decline buttons, and *Manage Owners*. Open the sealed answer, resolve the held
thread with "Reveal the planned answer" ticked, and confirm the answer then
appears on the plot page for everyone.

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


## Building foundations: private previews and transplant checks

The sandbox demonstrates Links 0.8.2 room rights, Maps 0.10 private stacks and
transplants, Regions 0.5 viewer-aware room pages, and Social 0.7 configuration
permissions. Install Links before its consumers; Social now declares Links
as a direct dependency. Existing commands and URLs supply the preview surface.

`seed_sandbox` creates **Private Draft Preview** and its upper floor, with two
OOC, secret rooms disconnected from the world. Its demo author controls them;
Builder staff can also preview them on `/map/`. Other visitors cannot discover
the planes through pages or API endpoints. Floor access shares the entry
room's privacy anchor. Resetting the demo replaces this disposable preview. Use the existing public
scratch plane for persistent digging experiments.

Run `+sandbox/builder on`, then `+sandbox/transplant` to see a read-only
translation of that two-floor draft northwest of the world-map origin. The
report lists proposed cells, blockers and unconnected neighbors and writes
nothing. The command is demonstration glue, not a player construction tool.

`world/sandbox/building.py` supplies one viewer-aware visibility callback for
Maps and Regions; the shared web-character middleware handles offline and
selected characters. Building now supplies Links permission/owner providers;
unmanaged rooms retain the host's control and visibility rules.
`world/sandbox/test_building.py` exercises
seed idempotence, selected-character SVG/live/API/region access, the transplant
command and Social's room-permission seam under the actual partners.

### Reviewed interiors

Building 0.3 is installed after Links, with the sandbox reveal switch enabled.
`BuildingRoomMixin` precedes `DefaultRoom` and `BuildingExitMixin` precedes
`DefaultExit`; keep cooperative `super()` calls so deletion, staff entry audit
and traversal checks run. `CmdBuild` is registered in the character command set.
The **My Building** page mounts `/building/` and the read-only API mounts
`/api/v1/building/`. The host composes Building's three-way visibility answer
with its existing private-preview rules for Maps and Regions.

`seed_sandbox` retains the **Residential Court** and **Residential Demonstration**
region with residential policy. **Demo Homeowner** owns **Sample Home**, an
approved unlocked two-floor home. **Demo Resident** has residence; its
**Restricted Bedroom** remains owner-only. **Two-floor Draft** is disconnected,
OOC and secret, and **Revision Requested** demonstrates the changes-requested
review loop. **Demo Building Reviewer** has the Builder permission for review.
These characters are generic demo objects, not additional login accounts.
Building content survives sandbox reset so proposals and ownership stay stable.

Use `help +build` or `/guide/building/` for authoring and property commands.
Staff can inspect the projects immediately. To test ordinary permissions, add
the homeowner and resident to separate nonstaff test accounts' playable rosters,
then select them in the web account menu. The homeowner can inspect the draft
and exact submissions; the resident sees the restricted upper floor disappear from map
names and counts. Unlocked entry alone never grants interior map access.
Jobs stores snapshot pointers; its generic questionnaires cannot submit the
Building-owned form. Native review continues when Jobs is absent.

`world/sandbox/test_interiors.py` exercises the actual room/exit MRO, review,
privacy, selected-character pages/API and contents-preserving cleanup.
The partner CI matrix also starts fresh processes with Maps, Regions, Jobs,
Economy and Social each absent, and all five absent together. It runs
file-backed review/withdrawal and quota races separately.

**Demo Apartment Owner** owns **Sample Apartment** inside Sample Home, with
recorded homeowner consent covering only the common entrance room.
**Demo Apartment Guest** has accepted an entry-only invitation. Lock Sample Home
to verify that the tenant and admitted guest retain passage, while the restricted
bedroom and parent floor plan remain private. `world/sandbox/test_apartments.py`
exercises this under actual room/exit composition, including deletion guards,
archive/restore, consent pages and Social/Maps privacy.

Staff `/archive`, `/restore` and `/quiet` use Building's shared lifecycle services.
The persistent `building_quiet_review` script checks daily using the existing
character-specific `sandbox_last_seen` activity provider. The runtime threshold
defaults to 35 days, with a reveal grace. Flags never change ownership/access.

## Combat practice

The Proving Grounds wires `evennia-rp-combat` after rules/chargen/NPCs.
Seeded sample builds carry an equipped Ready Guard Signature, Balanced
Tactics and combat Abilities (Flowing Guard and Calling the Shot, or Deflect
and Bait); the room has an empty open practice fight, so no PC is enrolled by
seeding. `world.ruleset.COMBAT_ABILITIES` holds neutral demonstration entries
for every combat 0.2 Ability and two Flaws (Telegraph, Off-Balance), seeded
only when combat is installed; `RP_RULES_EFFECT_KINDS` registers
`combat_rule` beside `combat_bonus`. Revive an incapacitated ally with a Heal
Assist they accept, then `+combat/recover`. `+combat/join side` explicitly accepts. See `/guide/combat/` and
`help +combat`; `+combatstory` is available to ordinary players, and its
changes to another player's character wait for that player's
`+combat/accept`. Use the Market's permitted NPC templates with
`/template blueprint=side,boss,cap` for an attributed practice opponent. NPC
stat blocks include all combat roles. `+combatstory/shelve` sets a fight aside
so the room and everyone's sheets are free; `/unshelve number` brings it back.

No typeclass mixin or new URL/API mount is needed. The package guide is
loaded by evennia-guides. Combat sends SYSTEM Scene entries without posing
or RP/XP credit, listens for real poses, and keeps separate NPC/controller
resources. Optional chargen validation uses `world.sandbox.glue`; removing
combat leaves the Signature library usable. The sandbox tests include
`world.sandbox.test_combat` for real partner seams. Run the integration gate
with `evennia test --settings test_settings.py typeclasses commands world`
and closed stdin; confirm a positive test count.

Combat exposes the optional `RP_COMBAT_PARTNERS` registry, with Party
registered here. Providers keep versioned fight data, freeze public packet
modifiers and append plain-text status/help through the contracts in
`contribs/rpg/evennia_rp_combat/PARTNERS.md`. The combat seam also checks
retained data and pending packets with a provider disabled. No additional
database migration, seed content or golden-database change is required for
this API alone.

## Party practice

`evennia-rp-party` follows combat in the install and app order. It needs no
typeclass mixin, new database table, URL or API mount. Its guide is available
at `/guide/party/`. The Proving Grounds seeds an empty Practice Formation
party on the practice side; no character is enrolled automatically. Join
the fight with `+combat/join practice`, inspect `+party`, then join the
displayed party identity. Another party or unpartied participation is valid.

Members choose Front, Back or Flex. Use `+party/formation back=on` to permit
Cover, then a same-party Front can `+party/cover defender=token,resist` or
preview with `/coverodds`. Cover and ordinary combat use the same frozen
packet inputs. Rally/Rattle entries are independent per supporter; Encore
spreads Spirit without spreading healing or revival. `+party/chat message`
is transient OOC delivery to connected members in the room, without Scene
entries, poses or RP credit. Authorized NPCs use `/as NPC=...`.

The settings block exposes provisional coefficients for host calibration.
Completed exchanges, hostile damage and outgoing Empower earn shared
Synergy. `+party/surge enemy=balanced` spends 100 to boost one packet's
primary output by 25%; `+party/surgepress` selects a later Burst hit. Support
and multi-target options are documented in the Party guide. Reservations,
refunds and once-per-personal-turn use share combat's transaction and journal.
Auto-Act never spends. Party 0.2 adds manual `+bosscheck`: an authorized
Boss Mode x2+ controller can issue Tank, DPS, Support, Pressure, Special or
Contest challenges to one or several named opposing Parties. Preview then
explicitly resolve, acknowledging pacing warnings with a public reason.
Targets may withdraw individually or cancel their Party's instance before
consequences commit. Formation stays flexible, but membership is locked;
committed consequences require staff recovery. Checks are never automated.
Contest freezes the host's stat vocabulary at enrollment/relock; it uses one
free bound response rather than an ordinary room test. See the Party guide
and `scripts/calibrate_boss_checks.py` for the authored practice workflow
and reproducible provisional defaults.
`world.sandbox.test_party` exercises real sheets, NPC control,
Calling the Shot previews, ignores, guides and chat. The independent CI job
also installs combat/Party wheels without optional packages, removes Party
while a populated fight is open, then reinstalls it and checks saved data
and packet continuity. The synthetic golden database includes the empty
practice party.


### Public frontier and shared settlement reference

From Residential Court take **frontier gate** to Frontier Demonstration. The
approved **Sample Settlement** has two public streets maintained by Demo Frontier
Lead, a recorded contribution by Demo Frontier Author, and a private Settlement
Home owned independently by Demo Settlement Homeowner. Exact reuse and ownership
agreements are retained. Reseeding preserves all generated identities and rights.
Use `/building/frontier/` for public growth and provenance; private home boundaries
are visible only through their owners' normal property controls. Staff see quiet
steward flags alongside property flags and must explicitly decide any reassignment.
The shared inactivity threshold defaults to 35 days; no automated action occurs.
Social 0.7.2 uses the narrow mood provider so stewards receive no configure rights.


### Disposable guest visits

After `seed_sandbox`, `connect guest` enters the Guest Lounge. Five guest slots
are available. `practice` leads to an OOC practice room; `+ooc` and `+home`
return to the lounge. Guests may finalize/test/reset their own builds, practise
posing, chat with `guest <message>`, page staff, and file `+request` or `+bug`.
Players can enter through `guests` at Arrival and join the Guest channel.

Guests cannot enter player areas, use join/summon/teleport to escape, receive
items, trade assets, post to boards, open scenes, or create shared challenges.
The movement rule also covers attempts initiated by another player or staff.
Guests earn no room/channel RP rewards, money or resources. Practice checks
produce no durable records. Guest sheets vanish on logout; staff tickets keep
their author-name snapshot. Website browsing is anonymous, and guests stay out
of permanent character lists/profiles. Connected who/where listings mark them.

`GuestCharacterMixin` is first in the Character MRO; `GuestAccountMixin` precedes
DefaultGuest. The explicit command sets in `commands/guests.py` use Replace so
newly installed commands are unavailable until reviewed. This public demo keeps
account registration open; invitation-only hosts disable it in their settings.
The reference game uses multisession mode 3 and 1000 character slots; accounts
create characters deliberately (`AUTO_CREATE_CHARACTER_WITH_ACCOUNT=False`).

### Moderation and reviewed admissions

Guests can use `+apply` in the guest wing. `seed_sandbox` creates a private
`SampleApplicant` ticket with a disposable author so staff can inspect
`+admissions`, `+jobs/form admission` and the rendered Jobs review page.
Reseeding preserves the sample's existing review decision. The public sandbox
also retains ordinary signup; hosts choosing reviewed intake disable direct
telnet and website registration separately.

`evennia_moderation` follows Jobs in install/app order. Its settings block
configures optional referrals with a game-wide allowance, uncapped intake,
the application questionnaire, the replacement authentication backend and
the middleware that rechecks existing website/API sessions. Staff use
`+softban`, `+mute`, `+notes`, `+admissions` and audited stock bans. Account
commands include a guarded stock page route so unpuppeting cannot bypass mutes.

`ModerationAccountMixin` precedes both account classes and `GuestAccountMixin`.
`CommunicationCharacterMixin` precedes Social/Posing and DefaultCharacter;
the existing Guest boundary remains first. The channel mixin precedes
DefaultChannel; RPTracker's IC channel already includes it. The server-start
hook ensures the daily retention sweep exists.

The staff-run marker is enabled on terminal and website character displays.
It uses current account roster status, including offline and quelled staff,
and current NPC controllers. Repeated alt co-presence produces one advisory
Jobs notice per account per seven days, once three overlapping room/channel
sessions occur in that window; it never flags sessions or changes XP eligibility.

`world/sandbox/test_moderation.py` covers real communication and authentication
routes, website board writes, private review context and the decline-reason
choice. CI also starts Moderation with its optional communication packages
physically absent, and runs file-backed admissions races. See the package
[README](../contribs/game_systems/evennia_moderation/README.md) for the complete
installation, runtime settings, retention policy and host integration signal.


### Crafting wave two

The market contains a sample brass lantern with room/smell/sound layers and a
sample carved lute. Pick up the lute and `use a sample carved lute = play`.
The host reveals wave two by default; set `RP_CRAFTING_WAVE_TWO_REVEALED=False`
for a separate staged rollout while leaving wave-one crafting on.
Use `+fixture`, `+smell`, and `+listen` to inspect the room. The public lantern
earns no furnishing credit. The catalogue adds Artisan and Decorator niches;
all opened lifecycle/verb sets are listed explicitly in settings.py.

`CraftingRoomMixin` precedes the host Room class to append description layers;
`CraftedFixture` puts the host stock-deletion guard before the contrib typeclass.
The same Links room providers support Social mood, permanent installation,
temporary decoration, lifecycle suspension, and property transaction locking.
Owners can write free sensory prose with `+roomconfig/smell` and `/sound`.
Five permanent fixtures and three temporary layers share one ambient emitter.
Fixture removal belongs to the property owner/staff, not permitted installers.
Temporary layers expire with their scene or timer and supply no cap credit.

Actual ownership-transfer/archive/restore, economy credit, ignore, scene logging
and combat-pause seams run in `world.sandbox.test_wave_two`. Crafting partner CI
also removes Building and Scenes physically, and the independent job tests only
Links/Resources/Crafting. Golden reseeding retires only tagged demonstration
placements; player fixtures and append-only craft history are preserved.

### Crafting wave three

The catalogue adds Enchanter and Companion Maker niches. Weavers can offer
dye services and Smiths can engrave. The market's sample lute has an attributed
aura; a sample clockwork bird stays in the market and has an Activatable bow.
Its owner can use `+pet/follow`, `/stay`, `/trick` and `/pose`. Pick it up
before gifting/selling it; ownership changes with ordinary handoffs and sales.

`+modify/offer customer/target = niche/modifier ; prose ; resource:quantity ; commission`
proposes a service; `+modify/accept number` consents and commits materials,
payment and the layer change once. `/layers target` lists layer numbers;
`/hide` and `/show` are free OOC toggles. `/undo customer/target = niche ; layer ; resources ; commission`
offers selected-layer removal. Base prose, equipment requirements and maker
history are preserved. Services require Economy; quiet Companions remain
usable with optional partners absent.

`ModificationDisplayMixin` precedes host objects/characters, and
`CompanionCharacterMixin` precedes the host Character with cooperative movement
hooks. Both imports are gated when Crafting is absent. The existing
Crafting command registration supplies `+modify` and `+pet`; there is no new web/API surface.
`RP_CRAFTING_WAVE_THREE_REVEALED=False` stages wave three independently.
Owner-written pet poses enter the ordinary posing pipeline. Automatic output
uses mute/ignore and scene emit logs without generating RP activity; ambients
pause offline/in combat. Real partner seams live in `world.sandbox.test_wave_three`
and run in the crafting partner matrix. The generated golden snapshot includes
the additive migration and synthetic demonstrations.

### Letters and signets

Market Row includes `a sample sealed letter`, addressed descriptively to the
Market Keeper, and `a sample rose signet` when Equipment is installed. The
Jeweller niche is explicitly permitted to make signets. Inspect the letter,
then use `read/contents` (keeps its seal intact) and `read` (opens it). The real
read command also handles cited letters through Lore's successful-read hook.

Carry the letter and signet to reseal with
`+letter/seal a sample sealed letter = a sample rose signet`. Its prior opening
remains visible, and enclosed journal writing/addressee stay frozen. Anybody
with normal read access may open it; the addressee is IC prose. Copies require
opening first, retain an editable addressee and honest authorship, and start
unsealed. `+craft/signet` adds a paid design to a Jeweller wearable draft;
`+craft/addressee` addresses a Readable or copy draft. `+letter` is wired in the
character cmdset. Without Equipment, the sample letter remains unsealed.
The synthetic golden database includes the new additive seal-state table and
these examples; reseeding retains earlier craft, opening and copy records.

### Item details and senses

Market Row's sample field book has a stitched `cover` detail, a paper-and-cedar
smell and a cloth texture. The sample lute has a quiet string sound and polished
wood texture. Try `look a sample field book = cover`, `smell a sample field book`,
`touch a sample field book` and `listen a sample carved lute`. Ordinary `look`,
`+smell` and `+listen` with no target retain the room's existing behavior.

The character cmdset installs Crafting's stock-look extension and shared sensory
commands. Item prose is private, comes from immutable paid craft metadata, and
never reads the book, activates the lute or produces room/RP output. Drafts use
`+craft/detail`, `/undetail`, `/sense` and `/unsense`; the reference setting charges
one extra resource unit per detail or sense. The generated synthetic golden
snapshot includes the seeded examples. Reseeding preserves earlier craft history.

### Wearable state demonstration

The sample woven cloak has `hood down` and `hood up` states. Carry it and use
`+adjust a sample woven cloak`, then `+adjust a sample woven cloak = hood up`.
Wearing it displays the selected variant. `+craft/state`, `/statedesc`,
`/defaultstate` and `/unstate` edit paid variants in a wearable draft. State
selection respects worn-item build locks and persists through outfits and
market sales. The host's CraftingCmdSet includes +adjust; Equipment's neutral
display provider seam keeps auras and Modifier layers visible once.

### Patterns

The seed adds two Spreading Patterns known to the seeded Sandbox Visitor.
**Market Lettering** is hallmark-only: `a sample lettered placard` shows
*"Worked in Market Lettering by Sandbox Visitor (Scribe)"*. With Equipment installed, **Verse Embroidery** opens
the otherwise closed wearable + readable combination for Weavers: `read a
sample verse scarf` reads the verse stitched into a wearable scarf. Both
niches still contribute and are paid for.

Try `+pattern/info market-lettering`. To teach, open a scene, have both
characters pose, then `+pattern/teach market-lettering = <character>` and
`+pattern/accept market-lettering`. Staff can `+pattern/create`, attach a
Pattern to a plot thread with `+pattern/thread`, and conclude the thread to
grant it to its participants. The reference setting moves Spreading Patterns to
Common after 42 days. `world.sandbox.test_patterns` covers the real posing,
scene and plot seams; the synthetic golden snapshot includes the examples.

Players propose new Patterns with the Jobs form registered in settings:
`+request/form pattern=<title>`, then `/answer` each question (name,
description, origin, niches such as `Weaver`, what makes it recognisable, an
optional combination and the reuse acknowledgement) and `/submit`. The web
form is at `/jobs/forms/pattern/`. Staff see what approval would create in
`+jobs <number>`; `+jobs/approve <number>.<revision> # <reason>` creates the
Pattern at Spreading, known to the proposer. Staff add tested combinations
afterwards with `+pattern/combo`. The reference game enables the form because
it reveals Patterns; a dark-launching game sets `"enabled": False` until then.
