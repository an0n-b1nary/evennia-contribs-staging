# Migration notes — evennia-rp-rules

## Origin and adoption

This preview is a contrib-native pilot. The generic kernel was authored
directly in staging, then wired into the reference sandbox and consumed by
the source project. It was not extracted from a working source implementation.
Games own their ruleset values and thin subject/vocabulary adapters; the
package contains no setting-specific stat names, domains or elements.

Install the pinned rules package before chargen or contest. Register
`evennia_rp_rules` before its consumers and set `RP_RULES_RULESET` to the
game's ruleset module. Use chargen's subject/vocabulary adapters for sheets,
or supply a game adapter returning a `StatSource` for stat blocks.

The kernel has no models or database migrations, and no source data import
is provided. Existing stats are not converted automatically. Validate a
game's ruleset with system checks and the odds tool before play.

## Resolution ownership

Stored ratings use rung keys and pip counts, so retuning hidden scores does
not require rewriting sheets. Future combat uses the kernel directly with
its own resolver and numeric mapping; it must not inherit contest's numbers
or import contest for resolution.
