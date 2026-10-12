# Combat partner contract (0.2.2)

Combat owns transactions, queues, costs, accepted inputs, personal clocks,
draws and rollback. A partner owns its own rules and versioned state. No
Party or Boss Check subsystem is provided by this API. Combat 0.2 owns
revival, recovery and its Ability rules.

## Registration and state

`RP_COMBAT_PARTNERS` maps a stable key to an installed app and a dotted
`partners.Provider` instance. The optional Party package uses:

```python
RP_COMBAT_PARTNERS = {
    "party": {
        "app": "evennia_rp_party",
        "provider": "evennia_rp_party.providers.PROVIDER",
    },
}
```

Combat checks the app registry before importing the provider. An absent
app is safe even if its provider module is physically unavailable. A bad
provider for a present app fails visibly and produces system check E008.
Registration is host configuration, never executable player input.

`state["partners"][key]` has exactly `{"schema": positive_integer,
"data": {...}}`. The owner supplies `upgrade(section)`, accepting `None`
for its initial state and returning its current envelope. Upgrades must be
deterministic and idempotent. Core `state.upgrade` detaches its input,
advances the core schema step by step (1 to 2 added partner sections; 2 to 3
added combat 0.2's participant fields), validates every envelope and calls
present owners.
It is used on normal loads and old rollback snapshots. It never writes
stored historical snapshots or changes frozen-build hashes.

An absent provider's envelope remains untouched, even if its internal
schema is newer than combat knows. Status/help report it as unavailable.
Removing a provider disables its modifiers, including pending packets.
Reinstalling restores saved inputs; a packet declared while absent keeps
its empty modifier snapshot. Old schema-1 packets also remain unmodified.

## Pure callbacks and frozen packet inputs

A `Provider` requires `snapshot(state, declaration)` and `upgrade(section)`.
Its optional callbacks are `transition(state, event)`, `status(state,
subject_id)`, `help(state, subject_id)`, `support(state, declaration)` and
`reserve(state, declaration, request)`.
All receive detached inputs.
No callback may query models, sample randomness, read live presence or
send messages. Transactions and authorization remain in the coordinator.
These are trusted engine extensions, not player or automatic policies.

`Declaration` contains actor/target identifiers, action, public Effects,
domain identity and behavior, exchange identifier and hit number. It deliberately has
no draw, hidden RPS bet or accepted reaction. The callback receives saved
fight state, so provider authors must keep public facts separate from any
private data in that state. Only the following validated `PacketModifiers`
fields reach reaction policies:

| Field | Meaning |
|---|---|
| `formation_penalty` | Nonnegative percentage points added to each defensive reaction's chance; not Accuracy tiers. |
| `damage_boost` | Outgoing damage percentage points, excluded from Burst Spirit transfer. |
| `surge` | Paid output percentage points; adds to damage boost and support Empower's multiplier. |
| `reaction_penalty` | Nonnegative percentage points removed from the defender's chance. |
| `cover_eligible` | Snapshot fact for the owning partner's interception UI/validation; not authorization by itself. |
| `auto_resolve` | Whether automatic acceptance is permitted for this packet; does not change the participant's saved opt-in. |
| `facts` | Up to 32 bounded public text pairs explaining values such as eligibility, average or positions. |

Numeric inputs are exact integer/Fraction/string values between 0 and 100,
serialized as rational strings. Floats, booleans and nonfinite values are
rejected. Multiple providers' numeric outputs add, capped at 100 per
field; automatic acceptance requires every provider to permit it.

The engine freezes outputs once for each target at declaration, and again
for each freshly pressed Burst hit. Later status/presence/support changes
do not recompute a queued packet. Manual resolution, neutral odds and
Auto-Resolve all consume those same frozen fields. Policies receive only
their normal capability-limited view and these public numeric values.

Damage boost/Surge modify outgoing damage before mitigation and the actual
Vitality-loss cap. Counterdamage is unchanged. Resist pressure uses boosted
damage prevented. Burst transfer instead uses pre-damage-boost damage,
including Surge, capped to the target's actual pre-hit Vitality. Support
Surge adds to support Empower (+50%); attack Empower keeps its existing
Power/Accuracy tiers. No party coefficients or resource-spending command
are installed by the foundation.

## Engine events and transaction boundaries

`transition(state, Event)` returns only the provider's own envelope, or a
`Transition(section, notices)` containing that envelope and bounded public
notice lines (tuple, each at most 400 characters, no newlines). Combat
validates and installs that result inside its current mechanical operation.
Mutating the detached input cannot modify other partners or participants.
Notices are journaled/announced with that operation, including notices from
`state_changed`; they are never saved as an unconsumed next-operation message.
Callbacks must use `event.kind` explicitly:

- `declare`: the new hit's modifiers are frozen and costs reserved.
- `packet`: a target's damage/support has executed; actual damage,
  counterdamage, healing, Spirit change and whether Empower applied are
  supplied. Participation flags describe eligibility immediately before
  hostile damage, so a defeating hit can still count. `potential_spirit`
  reports support output before the recipient's resource cap, allowing a
  successful capped Assist to qualify separately from a zero-effect attempt.
- `cancel`: an unaccepted target packet has been canceled.
- `exchange_end`: the actor's personal clock and allowance have advanced
  once, including exactly once for a Burst.
- `recovery`: the recovery action advanced its actor's allowance and clock;
  no attack or support executed and no action reward is implied.
- `hostile_damage`: attributed Poison suffered on an ordinary own exchange,
  with source actor, actual victim/loss and pre-damage participation. A
  recovery Poison tick emits no resource-reward event. Source-less or self
  Poison is not attributed hostile damage. The partner still checks sides.
- `state_changed`: before the coordinator journals any operation, including
  maintenance, shelving and rollback; use for saved-state reconciliation.

These are not separate commits. Failed operations roll them back together.
Service operation-id retries return their prior result without repeating
events. An accepted reaction is not a completed action or reward event.
Fight-local chat and live presence must stay outside partner state,
FightEntry snapshots and replayable callback results.

The package's post-commit `membership_changed` signal is still useful for
notifications. It cannot atomically apply a partner's damage, pool or
reservation changes and must not be used for that purpose.

## Explicit shared-resource requests

`engine.declaration`, `engine.press`, `services.declare` and the `press`
branch of `services.control` accept `partner_requests`, a mapping from
registered provider key to finite JSON options. Each request names `target`
as one of that hit's declared participant IDs. An empty target selects the
sole target of a single-target hit; it is invalid on multi-target actions.
The owning provider validates its remaining options. Auto-Act and ordinary
commands pass no requests and never choose partner spending.

Before freezing modifiers or automatically resolving, combat calls
`reserve(detached_state, declaration, detached_request)`. It returns its
own envelope or `Transition`, as above. This lets a provider reserve its
pool and per-turn marker, then expose paid output through `snapshot`.
An unavailable provider, wrong target, invalid request, failed affordability
or invalid callback return refuses the operation. Pure engine entry points
also use detached candidates for explicit requests, leaving their input
unchanged on failure. A requested but unaffordable Burst press refuses
instead of silently stopping. Ordinary unaffordable presses retain their
normal stop behavior.

The coordinator supplies NPC authorization, room/ignore consent, the Fight
lock, journaling, retry identity and automatic resolution. A provider never
owns a second transaction or changes other actors' resources. Refunds and
execution markers belong to its event handler; removing the provider keeps
its section untouched. Authors should reconcile saved cancellations/results
on return, without applying past output or replaying historical earning.
Request options are public journal identity, so they must contain no secret
draw, bet or private policy data.

## Support recipients

`support(state, declaration)` may return `None` or a `SupportSpread` with
distinct participant IDs and an exact Spirit-output factor between zero and
one. Only one provider may supply a spread for a packet. Combat applies it
only to Assist: it intersects the recipients with participating same-side
members and the coordinator's room/ignore filter. These are trusted saved
identities, never instructions to accept a revival or change membership.

The ordinary Spirit calculation, including Empower and each recipient's
repeat history, is scaled for each eligible recipient. The primary retains
its ordinary healing and riders; incidental recipients receive Spirit only,
without healing, hostile effects, Surge, additional costs, reward events or
resolved-target counts. The single-target Encore fallback is replaced when
a spread applies. With no spread it remains unchanged. The resulting
recipient IDs and outputs are saved with the exchange.

## Atomic interception

`engine.redirect(state, token, original_id, replacement_id, reaction, ...)`
is a supported primitive for a Cover service. The caller must first
authorize the actor/NPC and check party membership, Formation, standing
permission and all direct ignore crossings, then invoke it through
`services.execute` so the operation takes the Fight row lock.

The primitive validates an unaccepted packet, a same-side active replacement
with clear queues/outgoing exchange, and a legal Resist or Overpower. It
rejects partially accepted multi-target exchanges, replacements already
targeted by the exchange and another interception of the current hit.
It transfers the target, queue token and frozen modifier snapshot, then
accepts the chosen reaction in one detached candidate state. If validation
or reaction affordability fails, even the pure input state is unchanged.

The intercepted packet retains its original Formation penalty, hidden bet,
draw, costs and Empower. Optional `reaction_penalty` adds percentage points
for the interception. Evade is unavailable for this intercepted packet,
including its odds and policy enumeration. Later freshly declared hits
have the ordinary reaction choices and sample the replacement's position.

For a Burst, the replacement remains the target of the rest of the same
exchange. Ante/debt, hit count and existing Overextended carry forward.
The attacker may stop after the hit without further extension. Normal
opening/break rules and the three-hit limit apply. The primitive does not
allow multi-target Bursts or let an ally extend another actor's chain.
An exchange's retained redirect history also prevents a second Burst
handoff, even if the coverer changes Formation between hits.

`engine.interception_view(...)` validates the same detached handoff and
returns its public `ReactionView` without accepting or spending anything.
`services.describe_odds(view, token)` formats exact neutral odds, including
public Calling the Shot inputs, without revealing an ordinary hidden bet.

## Plain-text display

`status`/`help` return tuples of single text lines, each at most 500
characters. Combat sanitizes the lines before display. `+combat` appends
status; `+combat/help` lists installed partner help and directs readers to
the ordinary core command help. Display must respect the supplied subject
identity and must not leak private partner data to other participants.
