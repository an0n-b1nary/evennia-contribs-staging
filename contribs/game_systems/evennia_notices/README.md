# evennia-notices

A separately installable personal inbox for Evennia 6.0. Requires Links 0.8.15;
Social and all source contribs are optional. Add `evennia_notices` to
`INSTALLED_APPS`, register `CmdNotices` in the account cmdset, and include
`evennia_notices.urls` under the `evennia_notices` namespace.

Sources register through `LINKS_NOTICE_SOURCES` and own current visibility,
rendering and action resolution. No production source adapters are installed.
See the packaged [guide](guides/notices.md) for player commands and preferences.

## Host and source integration

Install `evennia-notices` and `evennia-links>=0.8.15`, register the app, command
and URLs, then call `ensure_notice_maintenance()` on server startup. Run
`evennia maintain_notices` to invoke the same idempotent maintenance manually.
`NOTICES_ENABLED`, `NOTICES_RETENTION_DAYS` and `NOTICES_ROUTINE_LIMIT` configure
the service. Call `validate_configuration()` after schema readiness; a cap
cannot be lower than retained distinct source groups.

Register `{source_slug: dotted_source_object}` in `LINKS_NOTICE_SOURCES`. A source
supplies `label`, batched `evaluate(events, context)` returning one `Evaluation`
per event ID, and `render(eligible_events, context)` returning plain text and
command/route instructions. Batches are scoped by source **and recipient**;
account and character transitions may legitimately share an event ID. Sources
own current permissions, action status, deadlines and safe viewer-relative names.
Only `lottery_selection` and `waitlist_offer` are outstanding action kinds.

Call `evennia_links.notices.notify(recipient, source=slug, event=event,
context=context, fallback=fallback)`. Use stable transition event IDs; replacement
keys identify slots separately. Payloads are bounded JSON primitives, never
trusted HTML or authorization. Optional route reversal safely falls back to
command instructions. Unknown/malformed data is an error; backend uncertainty
returns retry without invoking fallback. Inbox absence/clean disable invokes
only the supplied pending-store fallback, or the default safe connected renderer.
Offline default delivery returns `fallback_pending`, never a false acknowledgement.

For a future pending-store adapter, lock its source row and call `transfer` with
a stable transfer ID **inside the same database transaction**. Mark the source's
durable route receipt inbox-owned only after retained/duplicate/suppressed, and
roll back on retry. Preserve source history and reminder receipts. Old delivery
queries must exclude inbox-owned and previously fallback-delivered events.
Source receipts must survive inbox disable or physical removal: the removed
inbox cannot prove an old event was already consumed. Re-enabling must not replay
it. Socket hints are at most one attempt; the durable inbox survives hint failure.

This foundation installs no production adapters. Existing Calendar, Lore,
Moderation, Boards, Social page and payout queues keep their current behavior.
The reference game's `+sandbox/notices` is an explicit self opt-in to labelled
synthetic examples; confirm/decline commands simulate an offer for that player.
