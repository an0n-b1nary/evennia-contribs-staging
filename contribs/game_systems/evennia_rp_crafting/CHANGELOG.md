# Changelog

## 0.10.2 - 2026-10-18

- Add player guide pages for evennia-guides: `crafting` (workshops, drafts,
  kinds of item, hallmarks, details, senses and states), `crafting-letters`,
  `crafting-fixtures`, `companions`, `crafting-modifiers` and `patterns`; the
  glossary terms `glossary-workshop`, `glossary-hallmark` and
  `glossary-pattern`; and the design principle `breadth-not-quality`. Each
  page is hidden while `RP_CRAFTING_REVEALED` is off, and the fixtures,
  companions, modifiers and Patterns pages also follow their own reveal
  switches. The pages ship as package data.
- Require evennia-rp-resources 0.2.1 or newer, whose design principles the
  pages tag.

## 0.10.1 - 2026-10-18

- Add player Pattern proposals through an ordinary Jobs request form (the new
  `jobs` extra) with a settings-safe `pattern_form.FORM`. Approval by Crafting
  staff creates the Pattern at Spreading, known to its proposer; problems such
  as a taken key or name or an unknown niche roll the decision back, and staff
  review pages preview the result. Requested combinations stay staff-curated.
- Add `RP_CRAFTING_PATTERN_FORM` and additive migration 0009; existing Patterns
  and knowledge are unchanged.

## 0.10.0 - 2026-10-17

- Add Patterns: crafter knowledge with lineage. `+craft/pattern` stamps a
  verified "Worked in <Pattern>" hallmark, captured at craft time, and opens
  the Pattern's gated lifecycle/verb combinations for its listed niches only.
  Every contributing niche and cost still applies; there is no surcharge.
- Stages move forward only: Recovered until the origin plot thread concludes,
  then Spreading, then Common after `RP_CRAFTING_PATTERN_COMMON_DAYS` (runtime,
  default 90). Staff may advance a stage early; every change is logged.
- Teaching is offered and accepted, and needs a logged scene both characters
  posed in, active or closed within `RP_CRAFTING_PATTERN_TEACH_DAYS` (runtime,
  default 7). Same-account characters and guests cannot teach each other.
- Staff create and curate Patterns, grant them directly or attach them to plot
  threads, whose active participants learn them at conclusion. Players see
  only Patterns somebody knows, and only their own lineage.
- Add `RP_CRAFTING_PATTERNS_REVEALED`, an additive migration, a `plots` extra,
  reference-game examples and seams. Copies and Modifier services never carry a
  Pattern; existing records are unchanged.

## 0.9.3 - 2026-10-17

- Fix self-service Modifier acceptance to lock installed fixtures’ host property
  before characters, preserving SQLite write-first serialization and ownership checks.
- Show accurate open/completed/cancelled/expired service status across Economy
  and Crafting; allow local cancellation of already cancelled or expired offers
  without racing a completed acceptance.
- Replace raw numeric parsing errors in `+modify` with specific usage messages,
  preserving semicolons in service prose and explicit replacement terms.

## 0.9.2 - 2026-10-17

- Add paid wearable states with fixed crafter-authored variants and persistent holder selection through +adjust. Preserve craft snapshots, requirements, auras and Modifier layers. Worn selection follows the build lock. Use Equipment's neutral item-display seam; fixture/companion state consumers and automatic transitions remain separate.

## 0.9.1 - 2026-10-17

- Add paid named exterior details and self-directed smell, sound and touch
  facets on crafted items. Validate and capture bounded prose in the immutable
  craft snapshot; each entry adds a configurable resource cost.
- Add draft editing/removal, item-detail looking and targeted sensory commands.
  Keep ordinary looking and wave-two room senses, check local custody/view and
  sense locks, and keep inspection private and free of reading/consumption effects.
- Wire seeded reference-game examples, command seams and optional-partner checks.

## 0.9.0 - 2026-10-16

- Add paid, niche-gated signet designs and descriptive letter addressees.
  Using a signet requires custody, not a Workshop unlock; IC designs may be
  duplicated without claiming OOC identity.
- Open seals on successful page reads alongside optional lore grants. Contents,
  failed reads and previews leave them intact. Copying and journal history
  cannot bypass an intact seal. `composition.invoke(actor, item, "readable")`
  now performs that successful read: it returns the bookmarked page rather
  than the full text, moves the bookmark and notifies page-read partners.
- Permanently freeze enclosed journal writing and addressees when sealing.
  Resealing retains a previously-opened marker and impression count.
- Copies preserve editable addressees and honest text/source provenance, start
  unsealed and inherit no signet design or lore-citation authority.
- Add an additive LetterState migration and reference-game commands, seed
  examples, integration coverage and committed concurrency checks.

## 0.8.1 - 2026-10-16

- Share attributed delivery across Consumable/Broadcast, activations, fixtures
  and Companion events so Social ignore applies to their user/current owner.
- Log each affected room once, including adjacent Broadcast scenes, without
  creating participation, incrementing scene pose counts or recording RP
  activity. Owner-written pet poses retain the ordinary posing path.
- Keep wave-specific gates, ambient mute, remote account deduplication and
  post-commit delivery. Recipient or scene-capture failures do not prevent other
  deliveries. Scene logging uses the optional Scenes 0.8.2 capture API; older
  Accessibility or Scenes partners keep local output and skip what they lack.

## 0.8.0 - 2026-10-15

- Add optional facet validation, costs, immutable snapshot metadata and explicit
  successful-page-read hooks. Lore registers citations and recognition only when
  compatible partners are installed; missing providers hide their gated output.
- Share local reading target resolution with staff tomes. Keep contents and
  provider enumeration free of acquisition side effects and roll back failed
  reads together with their reading progress and lore acquisition.

## 0.7.0 - 2026-10-15

- Add blank journals with prepaid capacity, free owner writing, retained revision
  history and immutable page-writer identities across gifts and sales.
- Add reviewable copy drafts at normal crafting cost, freezing accessible text
  and its authorship with source lineage. Revalidate source access and content
  before spending; copy failures roll back payment, items and history together.
  A copy's binding takes the copier's own `/desc`, defaulting to the source's.
- Label hallmarks and text authorship as OOC. Keep binding makers separate from
  journal writers and copiers, and respect custom reader denial/redaction.
- Preserve shipped records with an additive migration; exercise journal gifts,
  sales, editions and reseeding in the reference host and partner-absence gates.

## 0.6.0 - 2026-10-15

- Readables support immutable authored pages, optional titles, contents and
  persistent personal bookmarks through the shared Links pagination helpers.
  Only multi-page books store bookmarks; a stale bookmark restarts at page 1.
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
