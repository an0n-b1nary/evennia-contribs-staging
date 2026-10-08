# Migration notes — evennia-rp-chargen

This preview package is a contrib-native pilot: the generic rules, sheets,
catalog and spending seam were authored here for consumption by the source
project. Games retain their ruleset values and thin adapters. No game-specific
stat names, domains or elements are required by this package.

## First adoption

Install pinned `evennia-links`, `evennia-rp-rules`, then this package, in
that app order. Run `evennia migrate --noinput`, configure the game ruleset,
allocation, catalog and subject/vocabulary adapters, then run
`evennia rp_chargen_seed`. Register the commands and wire IC poses to
`locks.note_ic_action`. Session-end release can use the configured tracker
integration; manual unlock and idle TTL also work without that partner.

There is no automatic import of an existing game's sheets. Keep legacy XP
as the ledger behind `RP_CHARGEN_XP_LEDGER` when retaining a native XP app;
the ledger must participate in the same database transaction. Starting
allowance is chargen-owned and must never inflate earned-XP totals.

## 0.2.0

Run `evennia migrate` to add `AbilityDefinition.budget_cost_overrides`.
Existing definitions default to `{}` and keep their flat `budget_cost`.
Template overrides use tag keys and resolve live on every loadout calculation;
an over-budget loadout stays equipped and is flagged until the owner adjusts it.

Earned XP remains optional. Install the `[xp]` extra, register `evennia_xp`,
migrate its `0002_xpspend`, and set `RP_CHARGEN_XP_LEDGER` to
`evennia_rp_chargen.integrations.xp.EvenniaXPLedger`. This service uses the
default database, so ability and XP writes share the caller's transaction.
Without XP installed, the adapter leaves starting-allowance purchases usable.
