# Changelog

## 0.1.1 — 2026-10-13

- Seat counting for `MODERATION_PLAYER_CAP` uses a fixed number of queries
  instead of loading every account. Guest, staff and retired-seat exclusions
  are unchanged, including hierarchical and plural staff permissions.

## 0.1.0 — 2026-10-13

- Account-wide timed bans, mutes, private notes, and audited stock bans.
  Staff commands are hidden from players' command matching and `help`.
- Atomic guest admissions, seat reservations, referrals and allowance periods.
- Shared authentication checks, offline notifications and address retention.
