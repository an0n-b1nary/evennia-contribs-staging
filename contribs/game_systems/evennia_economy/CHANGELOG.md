# Changelog

## [0.4.0] - 2026-10-22

- Breaking: credit and debit notes follow ` # ` after the amount; comma-separated notes are refused. Guard Economy and Shop switches before parsing, retain unique prefixes, and list Shop help forms separately. Allow Resources 0.3 in the optional extra.

## 0.3.3 - 2026-10-19

- Add a staff guide page for evennia-guides, `economy-staff`: the weekly run and stipends, adjusting purses, audits and review flags, shops, closing stalls, and freezing and revealing.

## 0.3.2 - 2026-10-18

- Add a player guide page for evennia-guides, `economy`, hidden while `RP_ECONOMY_REVEALED` is off. It ships as package data.

## 0.3.1 - 2026-10-14

- Let optional asset providers acquire host ownership locks before exchange character locks, so atomic crafting services follow the same lock order as property transfer. Existing providers remain unchanged.

## 0.3.0 — 2026-10-13

- Add property-bound shops, explicit stock disposition on transfer, archive suspension and reconciliation.
- Add an off-by-default local basic-resource seller with premium prices and audited currency sinks.
- Keep shop ownership, storefront purchases and system purchases inside the shared guest boundary.

## 0.2.4 — 2026-10-12

- Refuse asset exchanges involving guests; reward eligibility follows the guest-safe shared playable-character policy.

## 0.2.3 — 2026-10-10

- Fixed: market directory discovery (`+market`, `+browse`) skips stalls in rooms
  the viewer can't `view`, so a stall no longer reveals an undiscovered room's
  name. Staff still see every open stall.

## 0.2.2 — 2026-10-09

- Added: market directory search includes an optional item's
  `get_market_keywords(viewer)` hook, allowing niche discovery without
  importing crafting or requiring it to be installed.

## 0.2.1 — 2026-10-09

- Fixed: `evennia_economy.typeclasses` imports `DefaultObject` from its module,
  not the flat API, which is still unset when a management command such as
  `evennia check` loads host typeclasses through the URLconf. 0.2.0 crashed
  those commands in any game whose object typeclass uses `EconomyObjectMixin`.

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
