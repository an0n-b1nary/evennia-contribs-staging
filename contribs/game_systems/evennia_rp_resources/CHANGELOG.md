# Changelog

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
