# Changelog

## 0.2.0 — 2026-10-09

- Added: market-room stalls, reserved item/resource listings, offline atomic
  purchases, browsing and global discovery. Claim, listing and sale fees share
  their feature transaction; returning stock is free.
- Added: current stall ownership raises the passive money cap, with runtime
  controls for slots, per-character limits, cap raises and quiet-stall weeks.
- Added: quiet-stall and same-account drop/get review flags. Quiet stalls retain
  stock until explicit closure; floor pickup is allowed without penalties.
- Added: a cooperative market-room roster mixin, login-activity hook, generic
  sandbox market stock, real partner seams and live offline-sale acceptance.
- Upgrades retain the original migration and existing round-trip review flags.

## 0.1.1 — 2026-10-09

- Fixed: accept evennia-links 0.8 alongside 0.7 so the contrib installs with
  the shared web character resolver and its consumers.

## 0.1.0 — 2026-10-09

- Added: integer purses, atomic journaled currency writes, independent passive
  income with ownership-raised caps, taper and once-only eligibility/reveal stipends.
- Added: same-room atomic exchanges of money, items and optional provider assets,
  unreserved offers, secret acceptance, expiry and same-account protection.
- Added: fee boundaries, freeze/reveal controls, login summaries, reconciliation,
  account accrual reports and cross-asset round-trip review flags.
- `give` stays available while hidden (carried items only) and for item-only
  gifts while frozen, without a trade fee or an open-offer slot.
- The reveal stipend is paid once, to characters eligible when a game that ran
  hidden is revealed; never-hidden games and later characters don't receive it.
- The scheduler no longer sweeps stipends every minute, retries only failed
  characters with backoff, and pays periods missed while frozen on unfreeze.
- Deleting a character journals its balance as burned; post-commit item hooks
  run independently; the income-cap notice is given once, not weekly.
- Eligibility and same-account membership come from `evennia_links.characters`
  (links 0.7).
