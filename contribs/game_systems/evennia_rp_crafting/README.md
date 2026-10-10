# evennia-rp-crafting

Workshops unlock breadth, never quality. Invest money and resources in niches,
then compose new cosmetic items with **Wearable**, **Readable**, **Consumable**
or **Broadcast** behaviours.
Crafting has no XP, RP quota, quality tier or waiting period.

## Installation

Install `evennia-links` and `evennia-rp-resources` first, then `pip install -e .`.
Add `evennia_rp_crafting` after resources in `INSTALLED_APPS`, run
`evennia migrate --noinput`, and add `evennia_rp_crafting.commands.CraftingCmdSet`
to the character cmdset. There is no web/API surface or scheduler.

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
    "readable": {"base": {"materials": 1}},
    "consumable": {"base": {"provisions": 1}, "extra_beat": {"provisions": 1}},
    "broadcast": {"base": {"essences": 1}, "extra_beat": {"essences": 1}},
}
```

Staff own the code registry `RP_CRAFTING_BEHAVIOURS` (stable key → dotted class).
Each implementation provides `available`, `validate`, `cost` and `create`;
see `behaviours.py`. Niches list registered keys and allowed categories. Custom
implementations must return a new carried item and honour the caller's transaction.

## Provenance and review

Items show a separate **Craft hallmark** line from their immutable CraftRecord,
for example `Made by Morgan (Weaver)`. An item's editable description or
`db.hallmark` cannot alter this verified line. Wearables show it in `+gear/info`
through equipment's `get_display_provenance` hook. Item typeclasses put
`CraftedItemMixin` before the host object/equipment class in their MRO.
Hosts can set `RP_CRAFTING_READABLE_TYPECLASS` and
`RP_CRAFTING_WEARABLE_TYPECLASS` to subclasses of the shipped item classes.
Consumable and Broadcast also support `RP_CRAFTING_CONSUMABLE_TYPECLASS` and
`RP_CRAFTING_BROADCAST_TYPECLASS` with the same host guard ordering.
Put any early stock-deletion guard before those bases, as `example_game` does.

`+crafting/review` lists recent crafts; `/review <number>` shows full prose,
configuration, inputs, maker/account snapshots and the timestamp. No approval is
required. Records retain their original hallmark after a maker or niche is renamed
and survive deletion of the maker/item through integer soft references. Staff
administrative SQL is outside the player-service protection boundary.

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
