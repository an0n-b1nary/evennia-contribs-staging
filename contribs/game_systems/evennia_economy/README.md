# evennia-economy

Integer currency and consent-based exchanges for Evennia 6.x. Passive income
goes to eligible playable characters, including offline characters. No RP,
session count or login activity is required. A cap tapers income; earned money
and held balances never decay. Optional providers add counter assets without
coupling economy to their packages.

## Install

Install `evennia-links>=0.6,<0.7`, then `pip install -e .`. Add
`"evennia_links"` followed by `"evennia_economy"` to `INSTALLED_APPS` and run
`evennia migrate --noinput`. Links is the only hard contrib dependency.

Add `evennia_economy.commands.EconomyCmdSet` to your character cmdset, together
with `evennia_links.commands.CmdRuntime` for staff. The set replaces stock
`give` so direct gifts use the same account, freeze, fee and item safeguards.
Both stock `give item to character` and `give item = character` forms work.
Call `ensure_economy_script_running()` from `evennia_economy.scripts` in
`at_server_start()`. It checks income boundaries, first eligibility and offer
expiry every minute. No typeclass mixin or MRO change is required.

From your character's `at_post_puppet`, after `super()`, call
`evennia_economy.summary.notify_economy_summary(self)` for one quiet login line.
For immediate eligibility grants, an approval hook may call
`evennia_economy.batch.ensure_stipends(character)`; the scheduler also reconciles
these grants without requiring a login. Skip that call while frozen, or handle
`EconomyError`. Notifications are suppressed while hidden, even for staff.
There is no web/API surface in this release.

## Commands

```text
+balance                         purse and passive-income cap
+offer                           your open offers
+offer[/secret] character = 40 coins, resource:grain:3 for item:#12
+offer character = 3 Grain       a gift, with a resource provider installed
+accept[/secret] number
+offer/cancel number             either party can cancel
give item:#12 = character        immediate gift, using exchange safeguards
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

## Settings

The following are registered runtime controls, editable with `+runtime`.
Database overrides take precedence over host settings and defaults.

| Setting (`RP_ECONOMY_` prefix) | Default | Meaning |
|---|---:|---|
| `REVEALED` | `True` | Hidden commands/help for players; accrual continues |
| `FROZEN` | `False` | Refuse currency writes, fees, gifts and trades; keep reads/cancellation |
| `WEEKLY_AMOUNT` | `100` | Passive income before taper |
| `BASE_CAP_WEEKS` | `5` | Base cap as a multiple of weekly income |
| `TAPER_FRACTION` | `0.8` | Full income through this fraction of the cap |
| `STARTING_STIPEND` | `100` | Once at first eligibility |
| `REVEAL_STIPEND` | `100` | Once while revealed for each eligible character |
| `PERIOD_SECONDS` | `604800` | Monday-anchored batch period |
| `OFFER_TIMEOUT` | `600` | Seconds an unaccepted offer remains open |
| `MAX_OPEN_OFFERS` | `5` | Sent open offers per character |
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
  shared with resources. Default: every character in a playable account list.
- `RP_ECONOMY_STAFF_LOCK = "cmd:perm(Builder)"`.
- `RP_ECONOMY_FEE_POLICY = None`: callable/dotted path
  `(kind, actor, context) -> nonnegative int`. Default uses the runtime rates.
- `RP_ECONOMY_FLAG_REVIEW_HOOK = None`: callable/dotted path
  `(title, description) -> None`. With jobs installed, use
  `evennia_jobs.integrations.staff_review.file_review_job`.

Stipends are independently idempotent, even with a zero configured amount.
While hidden, only the starting stipend is paid. Revealing with `+runtime`
reconciles the reveal stipend after commit; the scheduler also catches deploys,
late eligibility and retries. Hide/reveal cycles never pay twice. Freeze creates
no income receipts; unfreezing allows the current completed period to retry.
The scheduler does not synthesize a historical backlog.

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
Optional `parse(text)` returns `(key, quantity)` or `None`. Providers must use
transactional counters, raise `EconomyError` on refusal and perform no external
work during the transaction. Native `money`/`item` kinds are reserved. Missing
providers reject affected offers while money and item exchanges keep working.
Resources 0.1.1 registers its adapter only when economy is installed.

Item transfers call `at_pre_give`, `at_pre_move` and the recipient's
`at_pre_object_receive` before changing the database location. Equipment's worn
restriction applies automatically. Cache updates, give/receive/post-move hooks
and notifications run after commit; a failed journal or partner credit rolls
the whole swap back. Post-commit hook failures are logged and cannot undo an
already committed trade. Host hooks must follow that distinction.

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
including after a character is deleted. Account accrual reports show all
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
