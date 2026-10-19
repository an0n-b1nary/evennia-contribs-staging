# Changelog

## 0.3.3 - 2026-10-18

- Rewrote the player guide in the guide format as two pages, both hidden while
  `BUILDING_REVEALED` is off: `building` (drafting, review, your home and
  apartments) and `building-frontier` (public places, collaborators, mixed
  settlements and stewards).
- `+build` help lists `+build/new frontier=<name>`, and the README's version
  line matches the package.

## 0.3.2 - 2026-10-14

- Expose room lifecycle and transaction locks for fixture consumers; allow explicitly requested inactive-owner lookup without awarding archived furnishing credit.

## 0.3.1 — 2026-10-13

- Expose an atomic property-transfer partner signal and explicit shop stock choice in commands and web forms.
  Only a trailing `;return` or `;transfer` selects stock; other semicolons stay in the transfer reason.
- Correct shop reconciliation guidance to use individual property identities.

## 0.3.0 — 2026-10-12

- Add public frontier and atomic mixed settlements with independently owned interiors.
- Add accepted collaborators, lead-only management and exact contributor/recipient agreements.
- Freeze explicit grid connections; validate mapped geometry or require manual staff certification.
- Add public stewardship, temporary mood permission, inactivity flags without automatic action,
  coordinated retirement, replacement connections and connectivity-preserving restore.
- Add selected-character web/command controls, public growth map/API/overlay and reference seams.
- Preserve 0.2 migrations, ordinary pending snapshots and apartment passage inside mixed homes.

## 0.2.0 — 2026-10-11

- Add exact-candidate attachment consent, independent one-level apartments and
  durable agreed passage for apartment owners, residents and accepted entry guests.
- Protect passage through parent locks, room overrides and transfers without
  granting parent editing, installation, remote presence or floor-plan rights.
- Add staff archive/restore preserving geometry, belongings and audit history;
  refuse child stranding and require both current owners for replacement passage.
- Add character-specific, deduplicated quiet-property review flags with a
  configurable 35-day threshold and reveal grace; never reclaim automatically.
- Add command/web/admin surfaces, generic apartment seeds and partner seams.

## 0.1.0 — 2026-10-11

- Add private interior drafts, frozen review snapshots, Jobs/native review and
  atomic promotion with individual ownership and audit history.
- Add residents, accepted invitations, private room overrides, locks, staff
  transfer and contents-preserving confirmed discard.
- Add reveal controls, optional partner adapters, command/web/API surfaces and
  a seeded reference game. Apartments and archive/restore remain future work.
