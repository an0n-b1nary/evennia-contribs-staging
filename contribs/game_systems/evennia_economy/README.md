# evennia-economy

Integer currency and consent-based exchanges for Evennia 6.x. Passive income
goes to eligible playable characters, including offline characters. No RP,
session count or login activity is required. A cap tapers income; earned money
and held balances never decay. Optional providers add counter assets without
coupling economy to their packages.

## Install

Install `evennia-links>=0.7,<0.9`, then `pip install -e .`. Add
`"evennia_links"` followed by `"evennia_economy"` to `INSTALLED_APPS` and run
`evennia migrate --noinput`. Links is the only hard contrib dependency.

Add `evennia_economy.commands.EconomyCmdSet` to your character cmdset, together
with `evennia_links.commands.CmdRuntime` for staff. The set replaces stock
`give` so direct gifts use the same-account, item-hook and ledger safeguards.
Both stock `give item to character` and `give item = character` forms work.
`give` never disappears: while the economy is hidden it hands over carried
items only (and mentions nothing else), and item-only gifts also work while
frozen and pay no trade fee, just like Evennia's own `give`. Coins and other
assets follow the freeze and fees. A gift never uses up an open-offer slot.
Call `ensure_economy_script_running()` from `evennia_economy.scripts` in
`at_server_start()`. Each minute it expires offers and notices a reveal; a
completed income period runs once, retrying only characters that failed, with
backoff. No typeclass mixin or MRO change is required.

From your character's `at_post_puppet`, after `super()`, call
`evennia_economy.summary.notify_economy_summary(self)` for one quiet login line.
Call `evennia_economy.batch.ensure_stipends(character)` from the login hook
and from any approval hook, so the starting stipend arrives when a character
first becomes eligible. It checks only that character and returns at once when
nothing is owed. The weekly batch also reconciles stipends without a login.
Skip that call while frozen, or handle `EconomyError`. Notifications are
suppressed while hidden, even for staff.
There is no web/API surface in this release.

## Commands

```text
+balance                         purse and passive-income cap
+offer                           your open offers
+offer[/secret] character = 40 coins, resource:grain:3 for item:#12
+offer character = 3 Grain       a gift, with a resource provider installed
+accept[/secret] number
+offer/cancel number             either party can cancel
give item:#12 = character        immediate gift (items only while hidden)
+economy                         staff reconciliation and account accrual
+economy/run [dry]
+economy/stipends
+economy/credit character=amount[,note]
+economy/debit character=amount[,note]
+economy/audit [character]
+economy/flags
+economy/reviewed number
```

An asset spec is comma-separated. Canonical forms are `money:40`, `item:#12`
and `<provider>:<stable key>:<quantity>`. Currency nouns and unique carried
item names work too. Resources adds `3 Grain` and `resource:grain:3`.
Both parties must share a room when offering and accepting. Leaving that room
expires the offer immediately, including leave-and-return teleports. Nothing
is reserved; acceptance checks current funds, items, partner availability,
expiry and playable-account membership again, then commits both legs together.
Five open sent offers and ten-minute expiry are the defaults.

Participants see the trade details privately. Others in the room see only
`A and B complete a trade.` Either party's `/secret` suppresses that room line.
Characters sharing any account's `account.characters` list cannot exchange
any asset, including gifts. Unaccounted NPCs are allowed. Hosts should route
other transfer commands through this API too; administrative object edits
remain outside this player-exchange policy.

An item dropped in a room and picked up by a different character on the same
playable account within seven days creates a staff review flag. Pickup is allowed.
Money and provider assets cannot be dropped. This observation covers ordinary
Evennia object location saves without a required item mixin; direct SQL edits
remain host administration.

## Stalls

Tag a room `market` in category `rp_economy`. Its `rp_economy_stall_slots`
Attribute overrides the runtime slot default. Characters may claim one stall
by default. Stock is reserved at listing: items move to a stall-owned container
with no location; provider counters are debited into the listing. A listing
contains one item or one resource lot, at a positive whole-number price.

```
+stall/claim My counter
+stall/name = A new name
+stall/desc = A description
+stall/list item name = 10
+stall/list resource:grain:3 = 5
+stall/unlist <listing number>
+browse [stall number]
+buy <listing number>
+market [name, description or stock search]
+stall/close [stall number]
```

Discovery is global, except for stalls in rooms the viewer can't `view` (staff see
every stall); purchases require the storefront's room. Sellers can be
offline. Purchase rechecks current account membership, stock, provider visibility,
buyer funds and item hooks; payment, fees, delivery, listing completion and ledger
entries commit together. A sold listing cannot sell twice. Seller sale fees come
from the proceeds. Listed items cannot be moved or destroyed outside the service.
Use rp-resources 0.1.3 or newer for returning archived resource stock.

Listed item typeclasses may expose `get_market_keywords(looker)`, returning
search terms in addition to their name. Crafting uses this optional hook for
niche names and behaviour keys, so `+market weaver` finds active woven stock.
Economy does not import or require crafting.

Quiet stalls are flagged once per inactivity period after five weeks without an
owner login, listing, unlisting or sale. They never close automatically. Call
`evennia_economy.stalls.note_login(character)` from the character login hook.
`EconomyBatchScript` checks inactivity. Flags use the existing staff-review hook
and `+economy/flags`; hook failures leave the local queue intact.

Owners close their stall locally. Staff may use `+stall/close <number>` remotely,
including during a freeze. Closure returns all active stock without fees and frees
the slot and cap raise. Restore a missing provider before returning its stock.
Close stalls before deleting an owner or market room; deletion otherwise refuses
to orphan reserved stock. Closed storefronts and their hidden stock containers
retain listing history.

For an early refusal before Evennia clears an object's attributes, put
`EconomyObjectMixin` before the host's base object/character/room class (or in
its shared object-parent mixin). The reference game wires it through
`ObjectParent`, gated when economy is absent. Database deletion guards also
protect reserved stock. Trusted reset code may call `stalls.recover(store_id)`
before rebuilding owners or rooms; that recovery API is not a player command.

Claim, listing, sale and upkeep boundaries default to zero fees. Upkeep runs
once per current income period after the claim period, pauses while frozen,
and retries shortfalls with one review flag per stall/period. It never closes
a stall or marks a shortfall paid. It does not back-charge every missed period.
If a host allows several stalls in one room, select one with
`+stall/list <stall number>/<item or lot> = price`.

For the one-line roster on `look`, put `evennia_economy.typeclasses.MarketRoomMixin`
before the host room class. It cooperatively extends `get_display_footer` and
does not constrain the order of other cooperative mixins. No web/API surface is
shipped by this release. Future crafting can extend catalogue discovery with its
niche vocabulary; this release searches names, descriptions and visible stock.

## Settings

The following are registered runtime controls, editable with `+runtime`.
Database overrides take precedence over host settings and defaults.

| Setting (`RP_ECONOMY_` prefix) | Default | Meaning |
|---|---:|---|
| `REVEALED` | `True` | Hidden commands/help for players; accrual continues |
| `FROZEN` | `False` | Refuse currency writes, fees, offers and non-item gifts; keep reads, cancellation and item gifts |
| `WEEKLY_AMOUNT` | `100` | Passive income before taper |
| `BASE_CAP_WEEKS` | `5` | Base cap as a multiple of weekly income |
| `TAPER_FRACTION` | `0.8` | Full income through this fraction of the cap |
| `STARTING_STIPEND` | `100` | Once at first eligibility |
| `REVEAL_STIPEND` | `100` | Once, at the reveal of a game that ran hidden |
| `PERIOD_SECONDS` | `604800` | Monday-anchored batch period |
| `OFFER_TIMEOUT` | `600` | Seconds an unaccepted offer remains open |
| `MAX_OPEN_OFFERS` | `5` | Sent open offers per character |
| `MAX_STALLS` | `1` | Open stalls per character |
| `STALL_SLOTS` | `8` | Market slots unless the room overrides it |
| `STALL_CAP_RAISE` | `100` | Money-cap raise per currently held stall |
| `QUIET_STALL_WEEKS` | `5` | Inactivity before staff review, never automatic closure |
| `FEE_<KIND>` | `0` | Flat whole-number fee at each named boundary |

The cap is `ceil(WEEKLY_AMOUNT * BASE_CAP_WEEKS)` plus links'
`cap_contributions` for `money`. Contributions are current ownership amounts
in coin; providers can convert their own UBI-week values before returning them.
Income tapers linearly near the cap, rounding up and never exceeding available
space. Trades, staff credits and stipends ignore that income cap. Zero-income
receipts are recorded so spending later cannot repay the same period.

Host settings (not runtime controls):

- `RP_ECONOMY_CURRENCY = ("coin", "coins")`.
- `RP_ECONOMY_ELIGIBLE = None`: callable or dotted path `(character) -> bool`,
  shared with resources. Default: every character in a playable account list,
  as `evennia_links.characters` defines it for every package.
- `RP_ECONOMY_STAFF_LOCK = "cmd:perm(Builder)"`.
- `RP_ECONOMY_FEE_POLICY = None`: callable/dotted path
  `(kind, actor, context) -> nonnegative int`. Default uses the runtime rates.
- `RP_ECONOMY_FLAG_REVIEW_HOOK = None`: callable/dotted path
  `(title, description) -> None`. With jobs installed, use
  `evennia_jobs.integrations.staff_review.file_review_job`.

Stipends are independently idempotent, even with a zero configured amount.
The starting stipend goes once to each character at first eligibility. The
reveal stipend is an event, not a second starting stipend: it is paid only when
a game that has run hidden is revealed, to every character eligible at that
moment, and later to anyone whose starting stipend predates the reveal (so a
failed sweep is made good). A game that is never hidden never pays it, and
characters first eligible after the reveal get only the starting stipend.
The reveal is noticed after a `+runtime` commit or, for a settings deploy, on
the scheduler's next tick; while frozen it waits for the unfreeze. Hide/reveal
cycles never pay twice.

Freeze creates no income receipts. Periods that complete while frozen queue up
and are paid, oldest first, once unfrozen. Periods that complete while the
server is down are not synthesized. A character whose payment fails is retried
alone, from five minutes doubling to six hours, for up to twelve attempts;
`+economy/run` reruns a period by hand at any time.

## Partner APIs and accounting

`services.credit`, `debit`, `balance` and `charge_fee` use whole integers.
Writes enforce the freeze and create the currency journal in the caller's
transaction. Money uses signed 64-bit storage; quantities outside that range
and overflowing credits raise `EconomyError`. A failed debit leaves no writes.

`exchange.create_offer(giver, recipient, give, want=[])` and
`accept_offer(recipient, offer_id, secret=False)` take canonical specs:

```python
[{"kind": "money", "key": "", "quantity": 40},
 {"kind": "resource", "key": "grain", "quantity": 3}]
```

`signals.asset_providers` collects `{kind: provider}`. Providers implement
`describe(key)`, `check(giver, recipient, key, quantity)`,
`debit(character, key, quantity, exchange_id)` and matching `credit`.
Optional `parse(text)` returns `(key, quantity)` or `None`. Optional
`available(character)` hides the kind from a character (resources uses it while
unrevealed): it neither parses for them nor trades with them. Providers must use
transactional counters, raise `EconomyError` on refusal and perform no external
work during the transaction. Native `money`/`item` kinds are reserved. Missing
providers reject affected offers while money and item exchanges keep working.
Resources 0.1.1 registers its adapter only when economy is installed.

Item transfers call `at_pre_give`, `at_pre_move` and the recipient's
`at_pre_object_receive` before changing the database location. Equipment's worn
restriction applies automatically. Cache updates, give/receive/post-move hooks
and notifications run after commit; a failed journal or partner credit rolls
the whole swap back. Post-commit hook failures are logged and cannot undo an
already committed trade. Each post-commit step runs on its own, so one failing
hook can't skip the item's `at_post_move` (where equipment seals a handed-over
item). Host hooks must follow that distinction.

`charge_fee(kind, actor, context)` is a nested transaction; call it inside the
owning feature's transaction. Named boundaries: `stall_claim`, `stall_upkeep`,
`listing`, `sale`, `trade`, `shop_approval`, `shop_upkeep`, `craft`. This release
executes `trade` for each nonempty outgoing leg. The remaining names are APIs
for later features. Nonzero fees have their own journal row with kind/reference;
a failed swap rolls fees back too. Policies should derive percentages from
the supplied context; default rates are flat and zero.

`signals.economy_figures` collects disjoint `{provider: figures}` for the staff
reconciliation report. Resources contributes its held units and ledger count.
Money journal rows retain character names, ids and playable-account snapshots,
including after a character is deleted. Deleting a character with a balance
writes a `deleted` journal row burning it, so minted minus burned still equals
held. Account accrual reports show all
playable characters' balances, UBI and stipends together. These are reports,
with no automated punishment.

If A sends any asset to B and B sends any asset to a different character on A's
account within seven days, a persistent review flag links both journal rows.
The asset kinds may differ. Flags never block, confiscate or notify players.
The review hook runs after commit; failures are logged and flags remain in
`+economy/flags`. Without jobs, leave the hook unset. Without resources,
money/items still work. No tracker, crafting, maps or jobs import is required.

## Verification and scope

Run `evennia test --settings=settings.py evennia_economy` in a migrated test
game with the fast MD5 hasher. Confirm the `Ran N tests` line. The repository
adds reference-game seams, isolated partner profiles and live two-session
exchange scenarios. Migrations support both fresh installs and adding economy
to an existing resources database.

Stalls, shop/listing models, storefront purchases, stall cap contributions and
system sellers belong to later releases. This release provides their fee and
accounting interfaces without exposing unfinished commands.
