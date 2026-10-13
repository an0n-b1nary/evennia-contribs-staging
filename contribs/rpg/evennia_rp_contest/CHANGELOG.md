# Changelog — evennia-rp-contest

## [0.1.4] - 2026-10-12

- Add a host-bound API to freeze rating/modifier sources, validate allowed
  approaches, resolve attempts inside the host transaction and validate
  binding/void status. Private audit records use existing migration history;
  the bridge has no combat dependency or post-commit mechanical signals.
- Bound attempts remain compatible with room history and never reveal ratings
  through the ordinary public-rating setting; staff review keeps the audit.
- Bound snapshots and durable attempts refuse guests, preserving disposable
  trial checks without shared participation or persistent audit writes.

## 0.1.3 — 2026-10-12

- Guest practice checks have no persistent audit record, challenge attempt or result signals. Guests cannot create or manage shared challenges.

## [0.1.2] - 2026-10-10

### Added

- A player guide page for evennia-guides, `tests` (`+test` and room
  challenges) and the `defaults-with-override` principle, in `guides/` and the
  package data. It describes the system in general terms, without exact numbers,
  and links only to pages this contrib or its required dependencies ship.
  Without evennia-guides it's ignored.

### Documentation

- Clarified preview pinning, the contrib-native origin and independence from
  chargen and combat; linked the reference integration and adoption notes.

## [0.1.1] - 2026-10-10

- Preserve an optional subject's `get_rp_actor_name()` in test audit records,
  public narration and scene logs, so NPC checks name their responsible player.
  Ordinary characters continue using their key; no NPC dependency is added.

## [0.1.0] - 2026-10-05

- Player-led `+test`, optional domain/element tags and suggestions, room
  challenges, retries, `/once`, setter/staff edits and retained void records.
- Private ratings, staff-only resolution audits, safe room narration and
  optional scenes/session integrations with idle expiry.
- Contrib-native implementation using the shared RP kernel; no chargen dependency.
