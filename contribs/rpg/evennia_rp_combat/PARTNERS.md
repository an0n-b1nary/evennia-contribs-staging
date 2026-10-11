# Combat partner contract (0.1.1)

Combat owns transactions, queues, costs, accepted inputs, personal clocks,
draws and rollback. A partner owns its own rules and versioned state. No
Party, revival, Boss Check or new Ability subsystem is provided by this API.

## Registration and state

`RP_COMBAT_PARTNERS` maps a stable key to an installed app and a dotted
`partners.Provider` instance. For example, a future Party provider may use:

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
advances schema 1 to 2, validates every envelope and calls present owners.
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
subject_id)` and `help(state, subject_id)`. All receive detached inputs.
No callback may query models, sample randomness, read live presence or
send messages. Transactions and authorization remain in the coordinator.
These are trusted engine extensions, not player or automatic policies.

`Declaration` contains actor/target identifiers, action, public Effects,
domain behavior, exchange identifier and hit number. It deliberately has
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

`transition(state, Event)` returns only the provider's own envelope. Combat
validates and installs that result inside its current mechanical operation.
Mutating the detached input cannot modify other partners or participants.
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
- `state_changed`: before the coordinator journals any operation, including
  maintenance, shelving and rollback; use for saved-state reconciliation.

These are not separate commits. Failed operations roll them back together.
Service operation-id retries return their prior result without repeating
events. An accepted reaction is not a completed action or reward event.
Future recovery must have its own event rather than simulate exchange end.
Fight-local chat and live presence must stay outside partner state,
FightEntry snapshots and replayable callback results.

The package's post-commit `membership_changed` signal is still useful for
notifications. It cannot atomically apply a partner's damage, pool or
reservation changes and must not be used for that purpose.

## Atomic interception

`engine.redirect(state, token, original_id, replacement_id, reaction, ...)`
is a supported primitive for a future Cover service. The caller must first
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

## Plain-text display

`status`/`help` return tuples of single text lines, each at most 500
characters. Combat sanitizes the lines before display. `+combat` appends
status; `+combat/help` lists installed partner help and directs readers to
the ordinary core command help. Display must respect the supplied subject
identity and must not leak private partner data to other participants.
