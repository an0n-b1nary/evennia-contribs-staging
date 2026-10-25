# evennia-rp-resources

Passive weekly resource accrual for Evennia 6.x RP games. Resource holdings
are atomic integer counters with an audited grant/spend ledger. Players choose
a persistent gathering lean that changes composition, never quantity. Income
does not require RP, sessions, login time or partner counts.

## Install and wire

Install `evennia-links>=0.8.4,<0.9` first, then `pip install -e .`. Add
`"evennia_links"` and `"evennia_rp_resources"` to `INSTALLED_APPS` in that order.
Links is the only hard contrib dependency. Maps, social, plots and economy
are optional; resources imports none of their models.

With economy 0.1 installed, resources 0.1.1 registers the `resource` exchange
asset and reconciliation figures during app startup. `+offer` accepts
`3 Grain`. Both resource ledger rows carry the exchange id,
and failed swaps roll both holdings and currency back. With economy absent,
resource commands, passive accrual and gathering work independently. While
resources are hidden, the asset provider's `available()` keeps them out of
non-staff trades and parsing, so nothing hints at them.

Add `ResourcesCmdSet` to your character cmdset and `evennia_links.commands.CmdRuntime`
for staff. Call `ensure_resource_script_running()` from
`evennia_rp_resources.scripts` in your `at_server_start()` hook. Add
`ResourceSummaryCharacterMixin` before `DefaultCharacter`, or call
`notify_resource_summary(character)` from `evennia_rp_resources.summary`
after your own `at_post_puppet` calls `super()`. The mixin is cooperative and
has no ordering requirement relative to other cooperative mixins.

Run `evennia migrate --noinput` and `+resources/seed`. A catalogue provider
is a dotted path or callable returning dictionaries:

```python
RP_RESOURCES_CATALOG = "mygame.catalog.resources"
RP_RESOURCES_CATEGORIES = [("materials", "Materials"), ("provisions", "Provisions")]

def resources():
    return [
        {"key": "wood", "name": "Wood", "category": "materials",
         "terrains": ["forest"], "weight": 2},
        {"key": "grain", "name": "Grain", "category": "provisions", "terrains": []},
    ]
```

Keys are permanent contracts: change labels or archive definitions instead
of renaming keys. Seeding updates listed definitions and never deletes omitted
ones. Archived holdings remain visible and spendable. `in_trickle=False`
reserves resources for explicit grants; automatic Plot Thread payouts are
scheduled for a later release.

## Controls and policy

| Runtime setting | Default | Meaning |
|---|---:|---|
| `RP_RESOURCES_REVEALED` | `True` | Expose player commands/profile fields and enable login summaries |
| `RP_RESOURCES_WEEKLY_QUANTITY` | `6` | Base units per batch |
| `RP_RESOURCES_BASE_CAP` | `30` | Five weeks of base income |
| `RP_RESOURCES_TAPER_FRACTION` | `0.8` | Full income below this fraction of the cap |
| `RP_RESOURCES_PERIOD_SECONDS` | `604800` | Monday-anchored batch duration |
| `RP_RESOURCES_LEAN_MULTIPLIER` | `2` | Weight multiplier for matching resources |

Use `+runtime NAME=<JSON value>` or `+runtime/reset NAME`; only registered
names can be edited. The database override wins over the host setting, which
wins over the package default. Changes are logged with the actor and send
`runtime_setting_changed` after commit.

Income tapers linearly between the threshold and the cap, rounded up to whole
units and limited to available capacity. Stocks never decay. Explicit grants,
trades and spending ignore the accrual cap. A links `cap_contributions` provider
can return `{"workshop": {"resources": 12, "money": 50}}` for the supplied
`character`. Provider keys must be distinct; only nonnegative integers count.
Without providers the base cap applies.

`RP_ECONOMY_ELIGIBLE` is an optional callable or dotted path `(character) -> bool`,
shared with economy. By default all characters in accounts' playable-character
lists qualify, including offline characters; membership comes from
`evennia_links.characters`, so every package agrees on who is eligible.
`RP_RESOURCES_STAFF_LOCK` defaults to `"cmd:perm(Builder)"`.

`RP_RESOURCES_OPEN_TERRAINS` accepts a collection, callable, or dotted path
returning a collection. `None` (default) scans the game's room typeclass family
each time the pool is needed (`+gather`, `+resources/catalog`, the batch), so
games with large grids should list their open terrains explicitly. Profile
fields never scan.
`RP_RESOURCES_TERRAIN_PROVIDER` accepts `(room) -> terrain key`; otherwise maps'
resolver is used when installed, falling back to the room's `terrain` tag
category. No regions dependency is needed. Empty terrain lists form an always
open common pool. Archived, payout-only and closed-terrain resources are
excluded from the trickle and new lean choices. Existing leans persist and
report when they currently yield nothing.

The scheduler checks every minute, so shortened periods need no restart.
Each completed period runs once. Characters whose accrual fails are retried
alone, from five minutes doubling to six hours, for up to twelve attempts (see
`evennia_links.periodic`); `+resources/run` reruns a period by hand. Periods
that complete while the server is down are not backfilled. Default labels are
ISO weeks. Changing duration creates a new
period namespace; staff should account for the transition when tuning it.
Hidden accrual continues normally and stops at the stock cap. A reveal
does not itself broadcast a message: announce it through your game's normal
channels and direct players to `+resources`.

## Commands and partner API

- `+resources`: holdings, accrual cap and last batch's gains.
- `+resources/catalog`: open trickle catalogue.
- `+gather [resource or category]`, `+gather/clear`: persistent composition choice.
- Staff: `+resources/run [dry]`, `/seed`, `/audit [character]`,
  `/grant character=quantity resource [# note]`, `/spend character=quantity resource [# note]`.

```python
from evennia_rp_resources.services import ResourceError, grant, spend

grant(character, "wood", 3, "exchange", exchange_id=42)
spend(character, "wood", 2, "Workshop investment", source="craft")
```

Reserved stock can be returned after its definition is archived with
`grant(character, key, quantity, "exchange", allow_archived=True)`. Ordinary
grants still reject archived keys. The optional economy provider's `refund`
method uses this recovery path; refunds remain journaled without unarchiving
the catalogue entry.

Quantities must be positive integers. Shortfalls raise `ResourceError`.
Counters update conditionally, and the counter plus signed ledger row share
the caller's transaction. Multi-character exchanges should lock all involved
character rows in ascending primary-key order before calling these helpers.
Never edit grant history or holdings directly.

`run_weekly_batch(week=None, dry_run=False)` in `batch` returns a dictionary
containing the period, allocations by character ID and errors. A zero-quantity
receipt records even capped or empty batches, ensuring a repeat cannot pay
again after a spend. Per-character transactions isolate failures; the script
retries failed batches. Random draws are seeded by character and period and
receipt metadata records the pool, weights, lean, prior stock and cap for audit.
Dry runs neither change counters nor consume receipts.

The login line names the week's gains. "Your stores are full" is said once
when stores fill; while they stay full and nothing is gained, no line is sent.

With social 0.3+, configure:

```python
SOCIAL_PROFILE_PROVIDERS = ["evennia_rp_resources.profile.gathering_field"]
```

Without maps, the tag fallback and common pool work without imports of any
optional partner.

With evennia-maps 0.9+, clicking a room on the live map shows a "Gathering here"
section in its room panel: the categories of resource tied to the room's terrain,
each with its resource names, and a note when the viewer's gathering lean matches
one. It gives no weights, quantities or odds. Players see nothing until
`RP_RESOURCES_REVEALED` is on, and nothing for a terrain outside
`RP_RESOURCES_OPEN_TERRAINS`, so a room in a stage that hasn't opened doesn't give
away what it will hold. Staff see a closed terrain's list, marked as not open yet.
The common pool is found everywhere, so it isn't listed. With
`RP_RESOURCES_OPEN_TERRAINS` unset, any terrain a room has counts as open, and the
panel doesn't scan the room typeclasses.

## Plot payouts

Install the `plots` extra (Plots 0.7.1+). Payouts attach to a **Plot**, not its
smaller Threads; Python keeps the `PlotThread` and `plot_thread_concluded`
names until Plots 1.0.

Owners or staff propose a per-participant budget:
`+resources/payout #<plot number>=2 rare-crystal`. Inspect with
`/payouts #<plot>`, remove a resource with `/payoutremove #<plot>=rare-crystal`.
Only staff authorize it with `/payoutapprove #<plot>`. Editing a resource clears
its approval. Conclusion refuses unapproved or archived budget resources.

Conclusion freezes approved amounts and the active `PlotParticipant` roster,
filtered through the same eligibility policy as accrual. Offline participants
qualify; ownership or Thread leadership alone does not. Awards ignore lean and
the holdings soft cap. Hidden systems pay dark; the Resource character mixin
shows each delivered award once at login after reveal.

Each recipient is paid atomically and has a durable receipt. Staff run
`+resources/payoutretry #<plot>` to finish interrupted awards. Repeats cannot
duplicate grants, late scene links cannot add recipients, and later eligibility
changes do not revoke an earned award. Archived resources still fulfill an
already frozen promise. Missing characters are skipped without redistribution.
Installation never backfills historical plots. Corrections use logged staff
grants/spends, not edits to a frozen award. Without Plots, accrual, holdings
and trading continue without importing or connecting its signal.

The catalogue's optional `basic` flag defaults to false. Economy's system
seller also checks `in_trickle`, archive status and explicit host prices;
it never sells payout-only rarity.

## Guide pages

The `guides/` directory holds pages for
[evennia-guides](../../utils/evennia_guides/README.md): a player page,
`resources` (also found as `gathering`), on weekly gathering, leans, the cap
and plot rewards; a staff page, `resources-staff`, on runs, the catalogue,
grants, audits and payouts; the glossary term `glossary-lean`; and two design principles,
`time-pays-quantity` and `nothing-decays`. The player page and the term are
hidden while `RP_RESOURCES_REVEALED` is off. They describe the system in
general terms, without exact numbers, and link only to this contrib's own
pages. Contribs that depend on resources, such as crafting, may link and tag
the principles. With evennia-guides installed they appear on its web guide;
without it they're ignored. To restate one for your game, add a page with the
same key to `GUIDES_DIRS`.

## Tests

From a game with links and resources installed:
`evennia test --settings settings.py evennia_rp_resources` (redirect stdin
and verify the `Ran N tests` line). The staging sandbox tests also exercise
real maps terrain resolution, social profiles, command registration, the login
hook and the generic seeded catalogue.
