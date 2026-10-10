# Changelog — evennia-rp-contest

## [Unreleased]

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
