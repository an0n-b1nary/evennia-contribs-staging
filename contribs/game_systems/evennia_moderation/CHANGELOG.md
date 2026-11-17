# Changelog

## [Unreleased]

- Mark `CmdAccountPage` as account-mode only; character-mode hosts mount
  Social's page instead. Add Builder-locked `CmdStaffAccountPage` (`apage`)
  with character/Staff public sender labels and private account attribution.

- Reject unknown, ambiguous and stacked switches before command lookups or changes, including stock command replacements.
- **Breaking:** use `ban <target>=<reason>`; reasons may contain colons. Keep invalid admissions numbers readable.

## [0.2.1] - 2026-11-16

- Route referral approval, decline and lapse through the optional shared Inbox
  with account-wide read/clear state, identity-safe rendering and source-owned
  historical provenance. Staff review jobs remain separate.
- Add generated migration0003, bounded retry/import command and durable routing
  receipts that survive Inbox disable/removal/restoration without replay.
- Keep independent source delivery; preserve unknown text-only history held
  rather than infer recipients, subjects, actors or reason-sharing from prose.
- Add reference opt-in simulation, rendered integration, actual package-absence,
  populated-upgrade and committed concurrency coverage.

## [0.2.0] - 2026-10-21

### Breaking

- Replace `+softban/lift/ip` with `+softban/liftip <address or CIDR>`.
- Replace `+admissions/decline/share` with
  `+admissions/declineshare <job>=<reason>`. Plain `/decline` keeps reasons private.
- Timed restrictions, notes and admissions reject stacked, unknown and
  ambiguous switches before changing state. Unique prefixes and
  case-insensitive switch matching remain available.

## 0.1.2 — 2026-10-18

- Guide pages for `evennia-guides`: a player page, `joining` (applying, referrals, restrictions and what staff can see), and a staff page, `moderation-staff`.

## 0.1.1 — 2026-10-13

- Seat counting for `MODERATION_PLAYER_CAP` uses a fixed number of queries
  instead of loading every account. Guest, staff and retired-seat exclusions
  are unchanged, including hierarchical and plural staff permissions.

## 0.1.0 — 2026-10-13

- Account-wide timed bans, mutes, private notes, and audited stock bans.
  Staff commands are hidden from players' command matching and `help`.
- Atomic guest admissions, seat reservations, referrals and allowance periods.
- Shared authentication checks, offline notifications and address retention.
