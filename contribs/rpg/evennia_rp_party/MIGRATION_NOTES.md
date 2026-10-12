# Migration notes

## 0.1.0 to 0.1.1

Install combat 0.2.2+ before Party 0.1.1. No model migration, core combat
schema change or build re-freeze is needed. Party's schema advances to 2
on load; each existing party starts at zero Synergy, with empty award and
reservation records. No earlier exchange grants retroactive earning.
Existing membership, Formation, Cover and support remain unchanged. Old
journal snapshots upgrade when restored; historical snapshots are not rewritten.

Keep the provider key `party` stable. Pending Surge reservations survive
package removal. While absent, combat uses no Party modifiers or earning.
On reinstall, executed packets keep their spent marker; canceled packets
refund once subject to the current cap. Pending packets keep the original
reservation and regain their frozen modifiers. No result is replayed.
Downgrading to 0.1.0 with schema-2 fights is unsupported and fails visibly;
restore a compatible backup or keep Party absent until upgrading again.

## Initial 0.1.0 install

No models or Django migrations are added. Combat must be 0.2.1 or newer.
Registration initializes a schema-1 Party envelope on load, including for
older retained combat fights. No existing participant is automatically
partied. Frozen builds and historical journal snapshots remain untouched.

After removal, combat preserves the envelope and disables Party modifiers.
Reinstall with the same stable provider key `party`; declarations made while
absent never gain modifiers retroactively. Back up populated fight data
before upgrades; staff rollback upgrades old checkpoint state on load.
