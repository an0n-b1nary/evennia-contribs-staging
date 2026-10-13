# Migration notes

## 0.1.1 to 0.2.0

Install links 0.8.4+ and combat 0.2.3+ before Party 0.2.0. Contest Checks additionally need
contest 0.1.4+ installed and registered as a Django app; the other five Check
types have no Contest dependency. Add `CmdBossCheck` if your host registers
commands individually; `PartyCmdSet` already includes it. No model migrations
are added. Party schema 2 upgrades to 3 with empty Check/issuance ledgers,
preserving existing Synergy and history without retroactive awards.

New combat enrollments/relocks capture a frozen optional Contest source.
Existing participants must explicitly relock before receiving a Contest
Check; rejoin alone preserves their original lock. Each Check retains the
issuance-time source across later corrections. Check attempts use the existing
Contest audit table and combat transaction; no ordinary room test counts.

Checks are manual storytelling beats. Stored NPC schedules remain unsupported.
Review the provisional presets and reference-game practice before adopting
the mechanics in authored encounters. Provider absence preserves saved data
and does not replay progress, consequences or awards on restoration.

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
