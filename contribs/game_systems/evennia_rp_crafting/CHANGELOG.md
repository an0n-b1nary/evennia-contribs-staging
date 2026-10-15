# Changelog

## 0.6.0 - 2026-10-15

- Readables support immutable authored pages, optional titles, contents and
  persistent personal bookmarks through the shared Links pagination helpers.
- Add draft `/page` and `/unpage`, explicit page breaks in `/text`, and numbered
  reads. Each additional page has a configurable material cost; total readable
  text remains bounded. Original single-text books retain their output and cost.
- Exercise paged books through the reference game's actual commands and seed.
  Journals, copies, mail, libraries and lore acquisition remain follow-ups.

## 0.5.0 - 2026-10-14

- Add niche-owned cosmetic Modifier services with exact, atomic consent/payment, selected-layer undoing, free OOC visibility and persistent provenance. Add transferable cosmetic Companions, follow/stay, owner poses, tricks and bounded automatic output; arrivals share the room EVENT limit, tricks still reach the room without Accessibility, and Companions refuse arriving objects before they move. Preserve existing data with an additive migration; wire the reference host and optional-partner gates.

## 0.4.0 - 2026-10-14

- Add reusable activation modes, random flavour readings, Installable fixtures, bounded temporary room layers, sensory commands, ambient scheduling, and captured furnishing credit in UBI-weeks. Preserve existing craft/item paths with an additive migration. Wire actual ownership, economy, scenes, ignore and combat partners in the reference host and test physically absent partners. A fixture supplies at most one temporary layer at a time, and deleting a room with `CraftingRoomMixin` returns its fixtures to the property owner.

## 0.3.0 — 2026-10-13

- Added: one lifecycle plus explicit compatible verb sets, with Readable
  dispatched from craft records and neutral Carried items retaining book prices.
- Added: combined niche access/cost validation, persistent verb drafts and
  contributor snapshots in hallmarks, staff review, market keywords and fee context.
- Changed: new craft records distinguish lifecycles and verbs. An additive
  migration preserves earlier snapshots, item paths, consumption records and drafts.
- Upgrade: hosts that register their own behaviours in `RP_CRAFTING_BEHAVIOURS`
  must also list them in `RP_CRAFTING_COMBINATIONS` (for example
  `"engraved": [[]]`); unlisted lifecycles are refused. Craft fee policies now
  receive `"carried"` rather than `"readable"` in `context["behaviour"]` for
  books; the Readable text is in `context["verbs"]`.
- Verified: reference-game books and optional equipment, economy and accessibility
  profiles; combinations remain closed to the original products by default.

## 0.2.1 — 2026-10-13

- Accept the compatible resources 0.2 and economy 0.3 releases.

## 0.2.0 — 2026-10-10

- Added: Consumable and Broadcast drafts with one to three paid EVENT beats,
  system-owned framing and canonical prose, and single-use consumption.
- Added: durable room audience limits, adjacent-room reach (Broadcasts never
  reach channels), optional accessibility mute, and use details in staff review.
- Added: additive migration preserving existing Workshops and craft history,
  reference-game Cook/Illusionist demos and live reload/mute acceptance.

## 0.1.0 — 2026-10-09

- Added: Workshops with escalating niche unlocks, a mandatory tunable active
  niche cap, abandonment without refunds, and ownership-based cap contributions.
- Added: registered Wearable and Readable behaviours, transactional resource
  spending and optional economy costs/fees, persistent player drafts, verified
  maker hallmarks and append-only craft snapshots for staff review.
- Added: generic reference-game content, live crafting/market acceptance and
  physically absent economy/equipment/accessibility partner profiles.
