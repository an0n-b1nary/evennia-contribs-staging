# evennia-rp-crafting

Workshops unlock breadth, never quality. Invest money and resources in niches,
then compose new cosmetic items with one **lifecycle** and compatible **verbs**.
Products include Wearables, Readables, Consumables, Broadcasts, reusable Activatables and Installable fixtures.
Crafting has no XP, RP quota, quality tier or waiting period.

## Installation

Install `evennia-links` and `evennia-rp-resources` first, then `pip install -e .`.
Add `evennia_rp_crafting` after resources in `INSTALLED_APPS`, run
`evennia migrate --noinput`, and add `evennia_rp_crafting.commands.CraftingCmdSet`
to the character cmdset. There is no web/API surface. A persistent room-ambient/expiry Script starts lazily on the first installation or temporary decoration.

Configure `RP_CRAFTING_CATALOG` as a callable or dotted path returning niche
dicts, then run `+crafting/seed` as staff. Keys are permanent: archive old niches,
never rename or delete them. Omitted catalogue entries are retained.

```python
def catalog():
    return [{
        "key": "weaving", "name": "Weaver", "description": "Cloth and trim.",
        "behaviours": ["wearable"], "input_categories": ["materials", "essences"],
        "unlock_money": 100, "unlock_resources": {"materials": 3},
    }, {
        "key": "writing", "name": "Scribe", "description": "Books and letters.",
        "behaviours": ["readable"], "input_categories": ["materials"],
        "unlock_money": 100, "unlock_resources": {"materials": 3},
    }]
```

## Commands

```
+workshop/catalog
+workshop/unlock weaving = timber:3
+workshop
+craft/new weaving/wearable = a woven cloak
+craft/desc = A soft cloak with a striped hem.
+craft/line = a woven cloak
+craft/slot = body
+craft/resources = timber:1
+craft
+craft/finish
+wear a woven cloak
+gear/info a woven cloak
+workshop/abandon weaving
```

For Readable, use `+craft/new writing/readable = a field book`, `/desc`,
`/text = ...`, `/resources`, then `/finish`. `read <item>` displays its text.

Authored pages use `+craft/page [title] = page text` repeatedly, then
`+craft/unpage <number>` to remove a draft page. `/text` replaces the draft's
pages; a standalone `---PAGE---` line in new text creates an explicit page
break. Page numbers do not depend on terminal width. Up to 100 pages fit within
the existing 12,000-character total, including titles (80 characters each).
Published pages stay in the immutable CraftRecord; these are not editable
journals. Each additional page costs `readable.extra_page`, defaulting to one
material input. Hosts with a custom cost map must configure that rule before
crafting multiple pages; old single-text books retain their original price.

`read <item> 3` or `read <item> = 3` selects a page. The equals form also works
for item names ending in numbers: exact whole-name matches take precedence.
`read/contents <item>` lists titles without moving the reader's bookmark.
`read <item>` resumes the last page read by that character, initially page 1.
Progress is stored in character Attributes under category
`rp_crafting_reading`, keyed by immutable craft ID, so renames and transfers do
not mix different books or readers. View and read locks apply to contents too;
commands search only carried items and the current room. Contents reads and
failed reads do not change progress. Single-page untitled books preserve their
original read output, and pre-existing text is never reinterpreted as pages.

Custom Readable implementations can supply `get_pages(actor, item, config)`
and return shared `Page` objects after checking access. An existing custom
`invoke` override remains authoritative: its returned text is one page until
the provider explicitly supports pages. Contents and numbered reads never
recover the raw text behind that provider's denial or redaction.

`item.read(reader, page=None, contents=False)` uses these reading rules.
`composition.invoke(reader, item, "readable")` retains the plain full-text
dispatch API for existing integrations, with page bodies joined by blank
lines. These operations do not grant lore or record poses. Journal authorship,
copies, seals, mail and library access remain separate follow-ups.
Drafts persist across logins and reloads. Preview consumes nothing; finish
revalidates current costs, niche access, freeze settings, inputs and funds.
Success clears the draft, so repeating finish cannot duplicate the craft.

Wearable also accepts `/aura` and repeated `/require` equipment rules;
`/unrequire <number>` removes a draft rule. Aura lines are cosmetic and appear
with the worn line. They consume additional essence inputs. Wear requirements,
build-change guards, worn-item movement refusal and sealing use equipment.
Crafted items are excluded from the plain-gear maker tag and its production cap.

## Consumables, Broadcasts and EVENTs

A Consumable emits one to three authored beats together, then is destroyed.
Each beat is plain, single-line prose of at most 400 characters. Formatting,
control characters and embedded `<EVENT>` markers are refused. The system
frames each beat using `RP_CRAFTING_EVENT_FRAME` (default `"<EVENT> {text}"`).
The prose and provenance come from the original CraftRecord; editable item
attributes cannot supply or replace an EVENT. Ordinary objects cannot use this
emitter. Effects are cosmetic: they do not grant stat changes or resource payouts.

Add a niche granting `consumable` with `provisions` inputs, or `broadcast` with
`essences` inputs, to your host catalogue. For example:

```
+craft/new cooking/consumable = a spice cake
+craft/desc = A small cake dusted with aromatic spice.
+craft/beat = A warm scent of spice fills the air.
+craft/beat = A faint sweetness lingers, then fades.
+craft/resources = grain:2
+craft
+craft/finish
use a spice cake
```

`/unbeat <number>` removes a draft beat. The first beat costs the base input;
each additional beat costs one more unit by default. A Broadcast uses the same
draft fields; `/reach = adjacent` is the default and only reach. It follows
visible, traversable exits one hop, deduplicates destinations, and never
recursively propagates. Broadcasts reach rooms, never channels, so they cannot
flood a game's chat or count as channel activity.

Install accessibility 0.3 or newer and register `mute_ambient_effects` and its
`+ambient` command as described in that package's README. The preference belongs
to the account and covers effects arriving from other rooms. In-room effects are
scene content and remain visible. Without a compatible accessibility partner,
Broadcast works only in the user's own room. Missing option registration mutes
remote effects for that account, preserving an effective opt-out.

Each item has one lifetime use. Source rooms and adjacent destination rooms
share a persistent cooldown, default 30 seconds, tunable through
`+runtime RP_CRAFTING_EVENT_ROOM_COOLDOWN` (1–86400 seconds). Limits survive reloads;
using a different item, user or source room cannot flood the same audience.
Cooldown, permission, hide, freeze or deletion refusals leave the item unconsumed.
Consumption and its use record commit together; delivery starts only after commit.
Delivery failures are logged without undoing the committed use. CraftRecord
survives consumption, and staff `/review <number>` includes the use identity and
destination snapshot. No scheduled beats or delayed callbacks survive consumption.

## Costs and caps

Unlock position is the number of **currently active** niches plus one. Cost is
the niche's base cost multiplied by `1 + UNLOCK_STEP * (position - 1)`.
Abandonment frees a slot, refunds nothing, retains investment history and lowers
the cap contribution. Re-unlocking pays the current position's price again.
Archived held niches still occupy slots until abandoned; they allow no new crafts.

Inputs are selected by stable resource key. Category totals must match exactly,
so one category cannot substitute for another. Archived resources cannot fund
new crafts or unlocks. Resources are spent through their public API; optional
money investment and the `craft` fee use economy's journal in the same transaction.
A failed creation, shortfall or journal write rolls back the whole operation.

Each active niche contributes configurable money/resource capacity. The raise
also covers any shortfall between the base cap and the most expensive next
unlock in the catalogue, including while at the niche cap. Tune the base cap
to cover the first unlock. Existing balances and stock never decay.

`RP_CRAFTING_COSTS` maps behaviour keys to category costs. Defaults:

```python
RP_CRAFTING_COSTS = {
    "wearable": {"base": {"materials": 1}, "aura_line": {"essences": 1}},
    "readable": {"base": {"materials": 1}, "extra_page": {"materials": 1}},
    "consumable": {"base": {"provisions": 1}, "extra_beat": {"provisions": 1}},
    "broadcast": {"base": {"essences": 1}, "extra_beat": {"essences": 1}},
}
```

Staff own the code registry `RP_CRAFTING_BEHAVIOURS` (stable key → dotted class).
Each implementation provides `available`, `validate`, `cost` and `create`;
see `behaviours.py`. Niches list registered keys and allowed categories.
Lifecycles implement `create`, returning a new item in the crafter's hands and
honouring the caller's transaction. Verbs instead implement
`invoke(actor, item, configuration)` and declare `role = "verb"`.

## Composition

Every item has one lifecycle: `carried`, `wearable`, `consumable`, `broadcast` or `installable`.
The lifecycle selects its typeclass and owns movement, equipment and destruction
hooks. `readable` is a verb, dispatched from the verified CraftRecord rather than
the item's typeclass. `+craft/new writing/readable` remains shorthand for a
Carried item with a Readable verb. Carried adds no cost or niche requirement;
the Readable verb retains the original resource price.

Only explicitly listed **complete verb sets** may be crafted. Defaults preserve
the original products and add the tested wave-two combinations. Standalone Carried objects remain closed:

```python
RP_CRAFTING_COMBINATIONS = {
    "carried": [["readable"], ["activatable"], ["readable", "activatable"]],
    "wearable": [[], ["activatable"]],
    "installable": [[], ["readable"], ["activatable"], ["readable", "activatable"]],
    "consumable": [[]],
    "broadcast": [[]],
}
```

An empty outer list permits no products for that lifecycle; `[[]]` permits a
lifecycle without verbs. A lifecycle missing from the mapping, including a
custom one registered in `RP_CRAFTING_BEHAVIOURS`, cannot be crafted. Listing `[["readable"], ["another_verb"]]` permits
each separately, never their union. Open each complete combination deliberately
with its own tests. The reference host opens exactly these tested combinations.

For a host that has tested wearable lockets, add `["readable"]` to its Wearable
sets. A crafter holding both contributing niches can then draft one with:

```text
+craft/new weaving/wearable = a locket
+craft/verb writing/readable
+craft/desc = A small locket with a note inside.
+craft/text = Meet me at the market.
+craft/slot = neck
+craft/resources = timber:2
+craft
+craft/finish
```

`/unverb <key>` removes an added draft verb. Preview and finish validate the
whole combination. Every contributing niche must grant its selected component;
finish requires all of them to be actively unlocked. Each component's resources
must fit its own niche's allowed input categories. Costs add once per component,
and the economy craft fee is charged once for the whole item. Holding another
niche that grants the same verb does not add a charge. Duplicate verbs and a
second lifecycle are refused. Existing equipment guards apply to composed gear.

The service entry points `craft` and `craft_cost` accept an optional `verbs`
list, with entries shaped as
`{"key": "readable", "niche": "writing", "configuration": {"text": "..."}}`.
They also accept `carried` with empty lifecycle configuration and explicit verbs.
The primary niche must contribute to the item. Fee policies receive the
lifecycle in `context["behaviour"]`, plus `verbs` and contributing niche snapshots.

The allow-list controls new production. Removing a combination prevents new
crafts without disabling existing items. Their actions still enforce runtime
permissions and installed-partner availability. Readable and Activatable are dispatched from verified record configuration. Companions, general facets and post-craft modification remain separate work.

## Provenance and review

Items show a separate **Craft hallmark** line from their immutable CraftRecord,
for example `Made by Morgan (Weaver)`. An item's editable description or
`db.hallmark` cannot alter this verified line. Wearables show it in `+gear/info`
through equipment's `get_display_provenance` hook. Item typeclasses put
`CraftedItemMixin` before the host object/equipment class in their MRO.
Hosts can set `RP_CRAFTING_READABLE_TYPECLASS` and
`RP_CRAFTING_WEARABLE_TYPECLASS` to subclasses of the shipped item classes.
`RP_CRAFTING_CARRIED_TYPECLASS` takes precedence over the Readable override;
the original `typeclasses.Readable` path remains a Carried lifecycle class.
Consumable and Broadcast also support `RP_CRAFTING_CONSUMABLE_TYPECLASS` and
`RP_CRAFTING_BROADCAST_TYPECLASS` with the same host guard ordering.
Put any early stock-deletion guard before those bases, as `example_game` does.

`+crafting/review` lists recent crafts; `/review <number>` shows full prose,
configuration, inputs, maker/account snapshots and the timestamp. No approval is
required. Records retain their original hallmark after a maker or niche is renamed
and survive deletion of the maker/item through integer soft references. Staff
administrative SQL is outside the player-service protection boundary.

New records store the lifecycle in `behaviour`, the verb configurations in
`verbs`, and all contributing niche keys/names/component grants in `contributors`.
Hallmarks, staff review and market keywords include every contributor and
component. The additive migration leaves earlier records intact; their Readable
configuration is interpreted as Carried + Readable without rewriting history.
Earlier saved drafts continue through the same single-behaviour shorthand.

## Runtime controls and partners

Use `+runtime` for `RP_CRAFTING_REVEALED` (True), `FROZEN` (False), `NICHE_CAP`
(5, minimum 1), `UNLOCK_STEP` (1), `MONEY_CAP_RAISE` (100) and
`RESOURCE_CAP_RAISE` (6), all with the `RP_CRAFTING_` prefix. Hiding removes
commands and help access for players; staff can test. Freezing prevents crafts,
unlocks, abandonment and item use; players can still compose drafts.
Reads and existing item appearances still work. Economy's freeze also prevents
new crafts/unlocks when economy is installed. `RP_CRAFTING_STAFF_LOCK` defaults
to `cmd:perm(Builder)`.

Hard partners: resources and links. Without economy, unlocks use resources only
and crafting has no money fee. Without equipment, Wearable is unavailable and
Readable continues to work and existing wearables remain ordinary crafted objects
with their hallmark. Accessibility enables muted remote Broadcast delivery.
Scenes and jobs are not used in this release. The reference game and
CI exercise actual partners and fresh environments with them physically absent.

## Activation and fixtures

`RP_CRAFTING_WAVE_TWO_REVEALED` is a separate runtime reveal control (default
True). Set it False to stage these features while keeping wave-one crafting
available. Ordinary players cannot unlock the new niches, compose or activate
wave-two features, or see fixture/sensory commands; room layers, new emissions
and furnishing credit are suspended. Staff retain service/command access for
testing. Existing wave-one items and reads continue unchanged. Global Crafting
hide/freeze controls still apply to both waves.

An Activatable is a reusable verb with 1-8 named modes. Each mode has 1-20
plain-text readings; activation selects one uniformly. Every extra mode and
reading has a configurable craft-input cost. These are cosmetic experiences:
they never replace system dice, grant lore, change combat, or advance posing.
Carried items require possession. Installed items allow visitors in the room,
subject to the item's `use` lock; using never grants editing/removal rights.

```text
+craft/new music/activatable = a carved flute
+craft/desc = A small carved flute.
+craft/mode play = A clear melody carries through the room.
+craft/resources = timber:1
+craft/finish
use a carved flute = play

+craft/new decoration/installable = a lantern
+craft/desc = A brass lantern.
+craft/room_line = Warm lamplight falls across the wall.
+craft/smell = A trace of beeswax.
+craft/sound = A faint candlewick hiss.
+craft/resources = timber:1
+craft/finish
+fixture/install a lantern
+smell
+listen
+fixture/uninstall a lantern
```

An interactive fixture adds `+craft/verb music/activatable` before its modes.
A playable wearable adds that verb to a Wearable draft; equipment's existing
wear/transfer/build guards still apply. Readable + Activatable Carried objects
and readable/interactive fixtures use the same record-based dispatch. The
crafter needs all contributing niches and pays the combined craft costs once.
Modes do not provide a game engine, verse sequencing or general state facets.

Installable configuration has `room_line`, `smell`, `sound` and `ambient`.
At least one line is required. Add `CraftingRoomMixin` before the host's Room
class to append layers cooperatively without overwriting room descriptions.
The reference host uses `+roomconfig/smell` and `/sound` for free owner-written
room prose; sensory commands show that prose before the attributed item lines.

Installation checks Links `install` permission, serializes the room, and moves
the object into it. Ordinary get/give/delete cannot remove an installed fixture.
Explicitly permitted residents may install, but only the current property owner
or authorized staff may uninstall. Uninstalled fixtures go to the property
owner, including when staff removes them. Public fixtures go to the removing
staff member. Property transfer retains fixtures; original craft provenance
never changes. Archive suspends layers, ambients and credit while preserving
objects. Restore resumes them. Visit the room to install, clear or uninstall.
Deleting a room with `CraftingRoomMixin` ends its temporary layers and returns
its fixtures to the property owner, or to the default home when there is none.
Without the mixin, a deleted room leaves its installed fixtures with no location.

### Temporary atmosphere

`+fixture/decorate <carried fixture> [= seconds]` publishes a temporary room
layer without permanently installing the object. It checks the same Links
`decorate` policy as Social `+mood`: owner/staff, public-scene active
participants, and private-scene hosts, including host mood-policy extensions.
It grants no `install` or `configure` rights. Layers expire at their associated
scene's close or their bounded timer, whichever occurs first. Without Scenes,
the timer is sufficient. `+fixture` lists layer numbers;
`+fixture/clear <number>` permits its creator, property owner or staff.
Temporary layers earn no cap credit and do not occupy permanent fixture slots.
A fixture supplies one temporary layer at a time and cannot be installed while
that layer is showing; clear it first.
Broadcast/Consumable lingering-illusion workflows remain a separate follow-up.

### Limits and output

Runtime controls, all prefixed `RP_CRAFTING_`:

| Control | Default |
|---|---:|
| `WAVE_TWO_REVEALED` | True |
| `FIXTURE_ROOM_LIMIT` | 5 |
| `TEMPORARY_LAYER_LIMIT` | 3 |
| `TEMPORARY_LAYER_SECONDS` | 3600 |
| `AMBIENT_INTERVAL` | 300 seconds |
| `ACTIVATION_ITEM_COOLDOWN` | 30 seconds |
| `EVENT_ROOM_COOLDOWN` | 30 seconds |

Permanent and temporary layers share one ambient emitter per room. Optional
ambient prose costs an additional essence. Accessibility is required to create
ambient fixtures; its physical absence silences existing emitters. Automatic
ambients respect ambient mute, avoid empty rooms, pause in open room fights,
and stop while Crafting is hidden/frozen or the room is archived. Item/room
cooldowns and emitter timestamps survive reloads. Delivery occurs after commit.
New activation/fixture emissions use the actor/current owner as `from_obj`,
respect Social ignore, and are logged as scene emits without becoming poses or
RP session activity. Broader legacy emission and reading-mode integration remain
tracked follow-ups. Screen readers receive plain item labels and EVENT text.

### Furnishing credit and host ownership

Only currently installed fixtures in live owned rooms raise the owner's money
capacity, through Links' `cap_contributions`. There is no overall furnishing
ceiling. Public rooms and temporary layers contribute nothing. Uninstalling
removes credit; reinstalling restores it. Property transfer changes the recipient.

Capture value once at craft time from the whole item's recorded inputs,
including composed verbs and the craft fee. Defaults:

```python
RP_CRAFTING_BASIC_FIXTURE_WEEKS = "0.2"
RP_CRAFTING_FURNISHING_REFERENCE = 1
RP_CRAFTING_FURNISHING_CATEGORY_VALUES = {"materials": 1, "essences": 2, "provisions": 1}
RP_CRAFTING_FURNISHING_COIN_VALUE = "0.01"
```

Value in UBI-weeks is basic weeks times weighted craft inputs divided by the
reference cost. Add weights for every host resource category. Commission,
purchase and resale prices never enter valuation; retuning input coefficients
affects new crafts only. Current weekly UBI remains the runtime coin scale.
Without Economy, crafting and fixtures continue; no money raise is supplied.
Ordinary furnishings do not raise resource storage.

Configure the shared room seams for Building hosts:

```python
LINKS_ROOM_PERMISSION = "evennia_building.access.room_permission"
LINKS_ROOM_OWNER = "evennia_building.access.owner_of"
LINKS_ROOM_LIVE = "evennia_building.access.room_is_live"
LINKS_ROOM_LOCK = "evennia_building.access.lock_room_state"
LINKS_OWNED_ROOMS = "evennia_building.access.owned_room_ids"
```

Custom lifecycle providers must return false for inactive rooms. The optional bulk-owned-room lookup
limits cap queries to the character's rooms; current ownership is revalidated
and item locations are fetched together rather than once per fixture. Without
this optimization, custom hosts retain the ordinary per-room owner lookup.
Lock providers must acquire the same transaction lock as ownership transfer, archive and access
edits; failures abort changes. Owner providers may accept `include_inactive=True`
for recovering archived fixtures; ordinary credit always uses the live lookup.
Without an ownership provider, Evennia control governs installation and no
furnishing credit is awarded. The additive migration preserves existing records,
typeclass paths and use history, with zero furnishing value on earlier records.

Wave-three Modifiers/Companions and the letterbox, library, places, map markers,
radius/bearings and remaining facet integrations are separate milestones.
