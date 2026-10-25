# Changelog

## [Unreleased]

- Reject unknown, ambiguous and stacked switches before command lookups or changes, including stock command replacements.
- Teach natural resource amounts in economy offers and keep invalid payout numbers readable.

## [0.3.0] - 2026-10-22

- Breaking: grants and spending use `<character>=<quantity> <resource> [# note]`; plot payout proposals use `<plot>=<quantity> <resource>`. Reject the old comma forms and invalid or stacked switches, retaining unique prefixes and the existing audit and payout approval services.

## 0.2.2 — 2026-10-19

- Add a staff guide page for evennia-guides, `resources-staff`: the weekly run, the catalogue, grants and spending, audits, and approving and retrying plot payouts.

## 0.2.1 — 2026-10-18

- Add guide pages for evennia-guides: the player page `resources` and the term `glossary-lean`, both hidden while `RP_RESOURCES_REVEALED` is off, and the design principles `time-pays-quantity` and `nothing-decays`. They ship as package data.

## 0.2.0 — 2026-10-13

- Add staff-approved plot payout budgets, frozen conclusion awards, retry receipts and login summaries.
- Mark basic resources explicitly for the optional system seller.
- Exclude guests from payout eligibility and budget management; reject resource counter overflow atomically.

## 0.1.4 — 2026-10-10

- **Added:** a "Gathering here" section in evennia-maps' room panel (0.9+): the
  resource categories and names tied to the room's terrain, with no weights or
  quantities, and a note when the viewer's lean matches. Players see nothing until
  `RP_RESOURCES_REVEALED` and nothing for a terrain outside
  `RP_RESOURCES_OPEN_TERRAINS`; staff see a closed terrain's list, marked not open
  yet. The common pool isn't listed. A patch release because evennia-rp-crafting
  accepts `<0.2`.

## 0.1.3 — 2026-10-09

- Fixed: returning reserved stall stock can restore archived resources, without
  reopening ordinary grants or unarchiving the catalogue entry. The optional
  economy provider exposes `refund`; `grant(..., allow_archived=True)` is the
  explicit host recovery API. Regression verified against the previous service.

## 0.1.2 — 2026-10-09

- Fixed: accept evennia-links 0.8 alongside 0.7 so resources install with
  the shared web character resolver and its consumers.

## 0.1.1 — 2026-10-09

- Added: gated economy asset provider for atomic resource exchanges, natural
  quantity/name parsing and staff reconciliation figures. Economy remains optional.
  Hidden resources stay out of non-staff trades.
- Fixed: one failing character no longer reruns the whole batch every minute;
  only failures retry, with backoff (links 0.7 `periodic`). Scripts from 0.1.0
  keep their last paid period.
- Fixed: "Your stores are full" is said once, not every week while full.
- Changed: eligibility comes from `evennia_links.characters`, shared with
  economy; profile fields no longer scan every room. Requires links 0.7.

## 0.1.0 — 2026-10-09

- Added: stable resource catalogue, atomic holdings and signed grant/spend ledger.
- Added: passive deterministic batches, eligibility policy, holdings taper,
  ownership cap contributions, persistent gathering lean and open terrain pools.
- Added: reveal controls, staff tools, quiet first-login summaries and optional
  social profile integration. Links is the only hard contrib dependency.
