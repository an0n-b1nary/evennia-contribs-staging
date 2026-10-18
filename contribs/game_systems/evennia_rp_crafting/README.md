# evennia-rp-crafting

Workshops unlock breadth, never quality. Invest money and resources in niches,
then compose new cosmetic items with one **lifecycle** and compatible **verbs**.
Products include Wearables, Readables, Consumables, Broadcasts, reusable
Activatables, Installable fixtures and cosmetic Companions. Niche-owned
Modifier services add attributed layers to existing items or characters.
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
Published pages stay in the immutable CraftRecord. Each additional page costs
`readable.extra_page`, defaulting to one material input. Hosts with a custom
cost map must configure that rule before crafting multiple pages; old
single-text books retain their original price.

`read <item> 3` or `read <item> = 3` selects a page. The equals form also works
for item names ending in numbers: exact whole-name matches take precedence.
`read/contents <item>` lists titles without moving the reader's bookmark.
`read <item>` resumes the last page read by that character, initially page 1.
Progress is stored in character Attributes under category
`rp_crafting_reading`, keyed by immutable craft ID, so renames and transfers do
not mix different books or readers. Only books with more than one page store
progress, and a bookmark past a custom provider's current last page restarts at
page 1. View and read locks apply to contents too;
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
lines. These operations do not grant lore or record poses. Seals, mail and
library access remain separate follow-ups.
Drafts persist across logins and reloads. Preview consumes nothing; finish
revalidates current costs, niche access, freeze settings, inputs and funds.
Success clears the draft, so repeating finish cannot duplicate the craft.

### Journals and editions

For a blank journal, start a Readable draft, set `/desc`, then
`+craft/journal = 10` and select resources for ten pages. Capacity is 1–100;
the base and extra-page rules price the binding and capacity up front. This
replaces any authored draft text. `/text` or `/page` replaces the blank journal
with an ordinary fixed Readable. Blank capacity also works on deliberately
allowed composed Readables; other components retain their own costs.

```
+journal/write journal = Arrival | We reached the market at dawn.
+journal/revise journal = 1 | Arrival | We reached the well at dawn.
+journal/history journal = 1
```

Any current holder can write without a niche, fee or material payment. Carry
the journal; view, read and write locks apply, as do crafting reveal/freeze
controls. Writing appends a page or revises one of that character's own pages.
Gifts and sales transfer writing rights through actual possession. A new owner
may add entries but cannot revise earlier owners' words; returning a journal
lets a previous writer revise their own entries again. Titles and current text
share the 12,000-character limit. Page numbers remain stable; deletion and
reordering are not supported. Existing printed books do not become editable.

Each revision snapshots its writer and timestamp in append-only history,
separate from the binding's CraftRecord. Every authorized history reader can
see earlier revisions, including replaced words; revisions are not erasure.
Reading shows the actual page writer under an explicit OOC label. Gifting or
renaming a writer never attributes old text to the binding maker or new owner.

```
+craft/copy journal = writing/a journal edition
+craft
+craft/resources = timber:2
+craft/finish
```

Copying needs the ordinary Scribe niche and full current Readable costs/fees.
There is no author-permission flag. Carry the source or stand beside it, and
retain view/read access through completion. The draft previews the authorized
pages, writers and price; changing source text requires a new draft. Copies
freeze the current text, titles and page authors. They remain unchanged after
source revisions, transfers or deletion. Copying an edition retains its writers
and records the intermediate source, rather than making its copier the author.
Only text is copied: other verbs, equipment rules, journal capacity, modifiers
and fixture properties are excluded. Copy drafts start with the source's
description; `+craft/desc` replaces it, since the binding is the copier's own
work. They otherwise accept resource selection, completion or cancellation;
rewritten pages start a new authored craft.

Custom reader denials and redaction remain authoritative. A provider's changed
text is copied exactly as exposed, with unknown authorship explicitly credited
to the host reader instead of guessing a page writer. Such providers cannot
expose raw journal history through the standard history command. No reading or
copy operation grants lore. The API entry points are `readables.write`,
`readables.history` and `readables.copy_book`; copy preview uses `snapshot` and
passes its fingerprint as `expected` at completion. Services revalidate locks,
possession, capacity, niches and costs within their transactions.

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

Every item has one lifecycle: `carried`, `wearable`, `consumable`, `broadcast`,
`installable` or `companion`.
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
    "companion": [[], ["activatable"]],
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
permissions and installed-partner availability. Readable and Activatable are
dispatched from verified record configuration. General facets remain separate
work; wave-three services preserve those original records.

## Provenance and review

Optional partners register paid metadata through `signals.collect_facets`.
`craft` and `craft_cost` accept a `facets` mapping; providers validate actor
rights and configuration and add their resource costs to the same transaction.
Normalized metadata is captured under `CraftRecord.prose["facets"]`. Unknown or
missing providers refuse new requested features. Existing records keep their
metadata but lose the absent provider's display/learning effects.

Lore 0.8 supplies `lore_citations` and `lore_recognition`, with `+lorecraft`
draft commands. Crafters must hold the referenced published lore. Recognition
adds one input per feature; citations do not change the Readable price. Refer
to lore's README for commands and limits. Metadata does not enter market
keywords or room rosters. Detailed look and equipment inspection use
`get_display_recognition(looker)` so holders see their own gated lines.

`signals.page_read` fires only for a selected, valid page, after access/provider
checks. It includes the actor, item, record, one-based number and a `canonical`
flag. Redacted/reordered custom provider output is not canonical and does not
authorize lore grants. Contents and raw `composition.invoke`/provider enumeration
never fire it. Reads are atomic with reading progress; hook responses can append
system-owned lines without replacing the crafter's text. Plain books retain
their original output when no partner contributes a line.

Owner-written journal revisions and citation-preserving copies require their
separate bridge; the fixed-page hooks do not yet implement those workflows.

Items show a separate **Craft hallmark (OOC)** line from their immutable CraftRecord,
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
Journal bindings list their actual writers separately. Editions add verified
"Copied by; text by" attribution and their source craft identity; these lines
come from append-only history, never item Attributes or the owner's prose.

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
All crafted emissions, including Consumable/Broadcast, use the actor/current
owner as `from_obj` and respect Social ignore. With Scenes 0.8.2 or newer
(`pip install evennia-rp-crafting[scenes]`), each affected room's newest
open/active scene receives one attributed emit, including adjacent Broadcast
rooms. Viewer mute/ignore does not remove shared log entries. Item output does
not start an open scene, create/rejoin participants, increment scene pose counts,
advance pose order or record RP session activity. Owner-written pet poses retain
their ordinary posing exception. Scenes remains optional; no scene capture is
attempted without it. Reading-mode integration remains a separate follow-up.
Screen readers receive plain item labels and EVENT text.

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

## Modifiers and consent services

Wave three adds `modifier_aura`, `modifier_mark`, `modifier_dye`,
`modifier_engrave` and `modifier_undo`. These are service behaviours granted
by niches, rather than lifecycles or verbs. The host catalogue assigns them.
Modifiers require Economy 0.3.1 or newer; service-only niches are unavailable without it,
while existing layers still render.

An offer identifies the exact target, added/replaced/removed layer,
maker-supplied materials, maker craft fee and customer commission. Offers
reserve nothing. Acceptance revalidates ownership, co-location, active niches,
target snapshot and current costs. A changed target or terms requires a new
offer. Materials, fees, payment, layer changes and acceptance commit together
once; failure rolls everything back. Economy's guest, same-account, freeze,
expiry, trade fees and ledger rules apply. Both parties' trade fees are shown
in the quote and revalidated on acceptance. Self services require explicit
acceptance and zero commission, but still consume materials and the craft fee.

```text
+modify/offer Mira/a cloak = weaving/modifier_dye ; The fabric is a deep red. ; timber:1 ; 30
+modify/accept 1
+modify/layers a cloak
+modify/hide 1
+modify/show 1
+modify/undo Mira/a cloak = enchanting ; 1 ; ember:1 ; 20
```

Service numbers and layer numbers are separate. Accept/cancel the returned
service number with `+modify/accept` or `/cancel`; its underlying Economy offer
also supports Economy's acceptance/cancellation commands. The recent-service
list labels each service as open, completed, cancelled or expired using both
its own deadline and the Economy offer's status/deadline. Listing changes no
records. Either participant can close an unapplied service with `/cancel`
after Economy has cancelled or expired its offer; completed services cannot
be cancelled. Repeated cancellation preserves the original cancellation time.
Aura, dye and
engraving have one active layer per kind; replacements explicitly name it as
the fifth offer term. Marks can coexist. Undo targets one existing layer with
the current owner's consent. Base prose, original aura lines, requirements
and unrelated layers remain intact. Replacement/undo retain removed layers
and their service/maker history. Hiding is a free OOC visibility toggle.

`RP_CRAFTING_COSTS` supplies service category costs: by default one essence
for aura, mark and undo; one material for dye and engraving. Hosts may subclass
Modifier behaviours. Resource keys and the setting-specific meaning of undoing
belong to the host. Services supply no stats or combat effects.

To restrict a service to particular resource keys, configure, for example,
`RP_CRAFTING_MODIFIER_RESOURCE_KEYS = {"modifier_undo": ["unmaking"]}`.
The key must exist in the host's resource catalogue; category costs still
come from `RP_CRAFTING_COSTS`. This permits a setting-specific undoing essence
without hardcoding it into the public service.

Put `ModificationDisplayMixin` before the host object/character in its MRO
for ordinary heirlooms and character marks. Crafted items already include it.
It appends visible attributed layers without altering base descriptions.
Equipment 0.1.3 also displays layers on plain gear and worn lines when Crafting
is installed. `+modify/layers` shows OOC history, including hidden/removed
layers. Public services: `modifiers.propose`, `accept`, `cancel`, `set_hidden`.
Economy's `service` asset cannot be gifted, listed or reoffered to bypass
the original consent/payment offer.

## Companions

`companion` is a cosmetic lifecycle; its tested complete verb sets are
`"companion": [[], ["activatable"]]`. Default cost: one material, plus one
essence for optional ambience. Activatable tricks require both niches and
their combined costs. `/arrival` and `/ambient` accept plain prose and require
Accessibility. Quiet Companions work without that partner.

```text
+craft/new companions/companion = a clockwork bird
+craft/desc = A little brass bird with decorative feathers.
+craft/verb music/activatable
+craft/mode bow = The little bird bows and spreads its wings.
+craft/resources = timber:2
+craft/finish
+pet/follow a clockwork bird
+pet/stay a clockwork bird
+pet/trick a clockwork bird = bow
+pet/pose a clockwork bird = tilts its head at the visitor.
```

Put `CompanionCharacterMixin` before the host Character, preserving cooperative
`super()` movement hooks. Following uses a traversable exit to the owner's
destination and respects entry/movement locks. Without a usable route it
stays behind and notifies the owner. The host exit's actual traversal hook
runs for the Companion; private routes may require explicit host permission.
Stay leaves it here; visit or carry it
to change modes. Pick it up before gifting/listing it. Ordinary handoffs and
Economy sales change ownership and reset it to stay; former owners lose control.
Companions have no inventory, puppeting, combat statistics or extra actions.
An independently acting animal belongs in NPCs.

Persistent ambients pause while the owner is offline, its room or owner's
room has an open fight, or Crafting is frozen/hidden. Arrivals, tricks and
ambients use owner attribution, scene emit logs, ambient mute and Social
ignore. They never record poses or RP activity. Without Accessibility,
tricks still reach the room as ordinary owner-triggered events. Owner-written
`+pet/pose` calls the owner's `record_pose(..., pose_type="emit")`, using
normal host tracking/capture once. Companion objects are hidden from viewers
ignoring their owner. Arrivals, tricks and ambients share persistent room
EVENT limits (an arrival inside the cooldown moves quietly); per-companion
ambient timestamps survive reloads. Companions refuse arriving objects, so
`give`/`put` report failure.

`RP_CRAFTING_WAVE_THREE_REVEALED` defaults True; use False for dark deployment.
Additive migration 0005 preserves earlier craft, fixture and use history.
Letterboxes, libraries, places, map markers, radius/bearings and remaining
facets remain separate milestones.

## Letters and signets

A letter is a carried Readable, including an owner-written journal. Set its
optional, descriptive IC addressee with `+craft/addressee = The Keeper` while
crafting, or `+letter/address <item> = The Keeper` while carrying it. Addressing
adds no resource surcharge and confers no exclusive reading permission;
normal object/view/read access still applies.

Hosts opt wearable niches into signet production with
`RP_CRAFTING_SIGNET_NICHES = ["jewellery"]` (default: no permitted niches).
Craft a Wearable from a permitted niche and add
`+craft/signet = The Courier's Rose`; `/unsignet` removes that draft feature.
The immutable `signet` facet records its design and contributing niche.
`RP_CRAFTING_COSTS["signet"]["base"]` adds one material input by default, on top
of wearable costs; custom cost maps must supply this rule. The contributing
niche must permit those categories and be unlocked. The service API accepts
`facets={"signet": {"design": "The Courier's Rose", "niche": "jewellery"}}`.
The existing combination allow-list still applies; no new verb combination
is enabled by a signet.

`+letter/seal <letter> = <signet>` requires carrying both items, write/read
access to the letter and view/use access to the signet. A worn signet counts
as carried. Using an existing signet requires no Workshop unlock and no
additional material or currency charge. Existing designs remain usable if
the host later removes the niche permission or Equipment package. New signet
production requires Equipment for the Wearable lifecycle. Sealing an empty
journal is refused.

The first successful text-page read breaks an intact seal and tells the
reader. Inspection and successful reads show its IC addressee, design and
intact/broken state; later readers also see any resealing marker. Contents shows a sealed notice without page titles; it does not
open the letter. Invalid page selections, denied reads and previews never
open it or grant lore. Seal breaking occurs inside the shared successful-read
transaction before optional lore grants. Copying and journal-history access
require opening an intact seal with an explicit page read first. They do not
silently open it, grant lore or move bookmarks.

Sealing permanently freezes **all enclosed journal writing and the addressee**,
even after opening. Resealing is allowed with a carried signet, but a permanent
"previously opened; resealed" marker and impression count remain visible.
The first-opening timestamp is retained. These bounded state fields avoid an
unbounded full-text or per-opening log. Craft and text authorship remain
unchanged. A design can be forged or shared IC; it never authenticates the
sender OOC. The seal is a physical roleplay affordance, not encryption.

Copies start unsealed with the source's descriptive addressee, editable with
`+craft/addressee` in the copy draft or `+letter/address` afterward. Copying
never clones a signet design, physical seal or lore-citation authority. Apply
a fresh seal using a possessed signet. Real page authors and source lineage
remain in OOC provenance. Draft review and completion recheck source access,
text/attribution, addressee and seal generation; resealing invalidates an old
draft even if the source is opened again before completion. Letterboxes,
delivery notices and journal-revision citation copying are separate features.

`LetterState` stores the physical addressee and seal state beside, rather
than inside, the immutable CraftRecord. Its additive migration preserves old
Readables, journal revisions and editions. Any carried Readable can be
addressed or sealed; `facets={"letter": {"addressee": "The Keeper"}}` initializes
that state at craft time. Existing books need no backfill. Object deletion
preserves state and signet provenance for staff review.

## Item details and senses

Every lifecycle may carry optional exterior `details` and `senses` facets.
These are immutable, attributed craft prose. Add them to an ordinary craft
draft before paying:

```text
+craft/detail hem = Tiny blue stitches follow the edge.
+craft/sense smell = A faint scent of cedar.
+craft/sense sound = Small beads click softly together.
+craft/sense touch = Soft cloth with a rough woven border.
+craft/undetail hem
+craft/unsense sound
```

Repeating a name replaces its draft entry. Preview with `+craft`; the detail and
sensory descriptions and combined cost are shown before `+craft/finish`. Removing the
last entry removes that facet. Existing `/smell` and `/sound` draft fields still
configure an Installable's room layers; `/sense` configures the item itself.
Copy drafts retain their existing text/binding workflow; exterior facets are
not automatically copied from the source.

The service API accepts:

```python
facets={
    "details": {"hem": "Tiny blue stitches follow the edge."},
    "senses": {"smell": "A faint scent of cedar.", "touch": "Soft woven cloth."},
}
```

Names match exactly after trimming and case folding. Up to eight details are
allowed, with names of 1–40 characters and prose of 1–1,000 characters. The three
optional sense keys are `smell`, `sound` and `touch`, each with 1–400 characters.
Names and prose must be plain single-line text without terminal markup; detail
names cannot contain `=`. Duplicate normalized names are refused.

`RP_CRAFTING_FACET_UNIT_COSTS = {"details": 1, "senses": 1}` sets positive integer
costs **per entry**. Each entry uses the first paid input category permitted by
the first contributing niche, in the existing composition order. A Cook therefore
pays provisions, an Illusionist essences, and an ordinary Scribe materials.
Custom settings must provide the applicable facet's positive unit cost. Costs
are revalidated at completion and captured in the ordinary craft record; there
is no ongoing cost for inspecting an item. Existing records need no migration.

Register `CmdLook`, `CmdSense`, `CmdListen` and `CmdTouch` from
`evennia_rp_crafting.commands`, or use `CraftingCmdSet`. `CmdLook` extends the
stock Evennia look command; hosts with their own look implementation can call
`item_details.examine(actor, item, name)` from it instead.

```text
look cloak = hem
look cloak hem
smell cloak
listen cloak
touch cloak
```

The complete object name takes precedence in the space-separated look form;
use `=` to disambiguate an item name and a detail. Ordinary object descriptions
list the available detail and sense names. `+smell`, `+listen` and `+touch` are
also accepted. With no target, `+smell` and `+listen` retain the wave-two room
prose and attributed fixture layers. Item senses follow the main crafting reveal
switch and work even when wave two is hidden. `touch` requires an item target.

Inspection requires an item in the character's inventory or current room,
`view` access, and the corresponding `smell`, `listen` or `touch` lock (default:
allowed). It cannot inspect another character's inventory or a remote dbref.
Only the caller receives output. It does not emit to the room, count as RP,
consume a use, activate an item, read a page, move a bookmark or grant lore.
These are exterior details: they convey no authority to read enclosed text.
Stored snapshots continue to work after gifting, freezing new crafting or
changing production costs. Plain objects cannot supply facets via Attributes.

## Wearable states

Wearables may carry a paid `states` facet: at most eight named, fixed variants
of their description and/or worn line, with one default. State names are
case-insensitive (1–40 characters), worn lines allow 200 characters and
variant descriptions 2,000. Prose is plain single-line text. Variants do not
change slots, requirements, auras, access, lore, item details/senses or verbs.
Base prose and the immutable craft snapshot remain intact.

```
+craft/new weaving/wearable = a hooded cloak
+craft/desc = A grey cloak.
+craft/line = a grey cloak
+craft/state hood down = a grey cloak, hood down
+craft/state hood up = a grey cloak, hood raised
+craft/statedesc hood up = A cloak with its hood raised.
+craft/defaultstate hood down
+craft/resources = timber:3
+craft
+craft/finish
+adjust a hooded cloak
+adjust a hooded cloak = hood up
```

`+craft/unstate <name>` removes a draft variant; removing the default selects
another remaining variant. Removing the last variant removes the facet.
Each variant adds `RP_CRAFTING_STATE_UNIT_COST` units (default 1, positive
integer) in the first contributing niche's first already-paid permitted
resource category. The preview includes this cost; each craft pays it once.

The holder may select a variant even after the item has changed hands and
its authored prose is sealed. `view:` and `adjust:` locks apply. Selecting a
worn item's state follows the character build lock; crafting pause/reveal
controls also apply. Selection produces only confirmation to the actor and
persists through restart, outfit changes and transfers. It does not activate
an item, consume it, emit room text or count as RP. Existing items without
states keep their current display. Previously crafted variants remain
inspectable if Equipment is removed. No schema migration is required.

Equipment 0.2.1 provides `evennia_rp_equipment.item_display.register`; Crafting
registers a base-state provider and a Modifier-extra provider during startup. Descriptions and worn lines apply
state presentation and visible Modifier layers once, with auras retained.
Wearable states are the first consumer; fixture, companion and activatable
state consumers, automatic transitions and timed states are separate work.

## Patterns

A Pattern is crafter knowledge, such as a recipe, schematic or weaving method.
It belongs to the character, not the item. Knowing one unlocks only what the
system enforces, never words: anyone may write prose in any style.

- **A verified hallmark.** Name a known Pattern in a draft with
  `+craft/pattern <Pattern>` (`/unpattern` removes it). The item's OOC hallmark
  reads *"Worked in Verse Embroidery by Kael (Weaver, Scribe)"*. The name is
  captured at craft time, so renaming a Pattern never rewrites old items.
- **Gated combinations.** A Pattern may list complete lifecycle/verb sets, in
  the same shape as `RP_CRAFTING_COMBINATIONS`, that are open only to crafts
  worked in it. The crafter still needs every contributing niche unlocked and
  pays the combined cost; a Pattern adds no surcharge and never makes an
  existing behaviour better. Only open combinations your host has tested. This
  package ships none by default.

One Pattern per craft. The draft's primary niche must be one the Pattern lists.
Copies and Modifier services never carry a Pattern.

### Stages

| Stage | How it is reached | Teaching |
|---|---|---|
| Recovered | A new Pattern starts here. | Not yet. |
| Spreading | The Pattern's origin plot thread concludes, or staff advance it. | Yes. |
| Common | `RP_CRAFTING_PATTERN_COMMON_DAYS` after Spreading (runtime, default 90). | Yes. |

The clock is read when the stage is checked, so retuning it applies to existing
Patterns. Staff may advance a stage early with `+pattern/advance`. Stages never
move back, and every change is logged. Later threads can still grant a Pattern
without resetting its stage. Common-stage learning is by teaching only; lore
entries, recipe books and premium sources are separate future features.

### Teaching

`+pattern/teach <character> = <Pattern>` offers to teach; the student answers
with `+pattern/accept <Pattern>` or `/decline`. The offer and the acceptance
each check that:

- the teacher knows the Pattern, it is Spreading or Common and not archived;
- the student does not know it yet;
- neither is a guest, and no account lists both characters;
- both posed (not just observed) in the same logged scene, which is still
  running or closed within `RP_CRAFTING_PATTERN_TEACH_DAYS` (runtime, default 7).

One logged scene is enough however long it ran. Whether a lesson costs
anything is for the players to settle in character. Without `evennia-scenes`
nobody can teach. The scene is recorded in the student's lineage.

### Curating and granting

Staff (`RP_CRAFTING_STAFF_LOCK`) use `+pattern/create <key> = <name>` (keys are
permanent), `/describe`, `/rename`, `/niches`, `/combo` and `/uncombo`
(`<lifecycle>:<verb>[+<verb>...]`), `/grant <Pattern> = <character>`,
`/archive`, `/unarchive` and `/roster`. Archiving blocks new crafts, grants and
teaching; existing items and knowledge are unchanged.

With `evennia-plots` installed (the `plots` extra),
`+pattern/thread <Pattern> = <thread id>` attaches a Pattern to a proposed or
active thread. The first attached thread is its origin. When the thread
concludes, its active, playable participants learn the Pattern, the grant is
frozen with its recipient list, and an origin Pattern moves from Recovered to
Spreading. Repeated conclusion signals grant nothing twice.

### Visibility

`RP_CRAFTING_PATTERNS_REVEALED` (runtime, default True) hides Patterns from
players while the main crafting reveal is on. Players see only Patterns that
somebody knows, so staff can prepare a recovery without spoilers. `+pattern`
lists your Patterns and offers, `/all` the known ones, and `/info` the name,
description, niches, gated combinations, stage and number of knowers, plus your
own lineage. Only staff see other characters' lineage, with `/roster`.

Additive migration 0008 adds `Pattern`, `PatternKnowledge`, `PatternOffer`,
`PatternThreadGrant` and `PatternStageChange`. Existing craft records and
items are unchanged.
