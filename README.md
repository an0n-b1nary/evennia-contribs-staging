# evennia-contribs-staging

A preview channel for [Evennia](https://www.evennia.com/) contribs in active development.

> ⚠️ This repository is a **preview channel for Evennia contribs in active development**. APIs may change. Shipped migration history is preserved; upgrades still need verification against your data. Each contrib here is intended to eventually submit to [`evennia/evennia`](https://github.com/evennia/evennia) upstream. Pin specific commits if you depend on a package.

## What this is

A mono-repo of draft Evennia contribs being staged before upstream submission. The layout mirrors Evennia's own `contrib/` category structure (`base_systems/`, `game_systems/`, `rpg/`, `utils/`), so a contrib's path here is the same path it will have inside Evennia upstream after acceptance.

Each contrib lives in its own subfolder with its own `README.md`, `CHANGELOG.md`, and install instructions.

## What this is not

- **Not** a production-ready library. Pin commits if you depend on anything here.
- **Not** an upstream replacement. Once a contrib lands in Evennia, its copy here is frozen and deprecated in favor of the upstream version.
- **Not** a fork of Evennia. These are additive contribs intended for Evennia's `contrib/` tree.

## Installing a contrib

Each contrib is installable as a pip subdirectory dependency:

```bash
pip install "evennia-<name> @ git+https://github.com/an0n-b1nary/evennia-contribs-staging.git@<full-sha>#subdirectory=contribs/<category>/<contrib_name>"
```

See the per-contrib README for `INSTALLED_APPS`, settings hooks, and wiring details.

## Repo layout

```
contribs/
├── base_systems/    — shared infrastructure (e.g. evennia-links)
├── game_systems/    — domain contribs (events, lore, xp, jobs, boards, etc.)
├── rpg/             — RP-flavored contribs
└── utils/           — small standalone utilities (e.g. evennia-accessibility)
```

## Contrib roadmap

The repo is being populated incrementally. The full anticipated slate, grouped by role:

**Foundation**
- `evennia-accessibility` (utils) — 0.3.0; screen-reader helpers, account ambient mute, accessible Django forms, MXP link conventions
- `evennia-links` (base_systems) — shared bridge-model base classes, edit-history & soft-delete mixins, optional notification dispatcher

**RP infrastructure** (all but the posing/social layer depend on `evennia-links`; posing and social are model-free and depend only on each other)
- `evennia-posing` (game_systems) — the pose pipeline: pose/emit/semipose capture, pose-order tracker, pose headers, name highlighting; foundation other RP systems build on
- `evennia-social` (game_systems) — social QoL layer on evennia-posing: profiles, player/venue discovery, page, ignore/mute, consensual teleportation, OOC chat, navigation shortcuts
- `evennia-regions` (game_systems) — geographic grouping of rooms with soft-archive, web views, and a region label on every mapped tile
- `evennia-maps` (game_systems) — a 2D coordinate map of your rooms, auto-grown from canonical exits, with a BFS reflow engine, an SVG + Leaflet web map, and a signal seam other contribs light overlays through
- `evennia-rptracker` (game_systems) — pose tracking and RP session recording
- `evennia-jobs` (game_systems) — staff job-request workflow with anti-favoritism patterns
- `evennia-lore` (game_systems) — wiki-style knowledge entries with approval queue, version history, region-weighted passive discovery
- `evennia-xp` (game_systems) — pluggable XP collection, login summaries, projected earnings and atomic spending/refunds (preview 0.4.0)
- `evennia-boards` (game_systems) — flat bulletin boards with subscriptions and post versioning
- `evennia-scenes` (game_systems) — scene logging with live entries, participants, web surface
- `evennia-calendar` (game_systems) — events, RSVP, optional cluster-lottery seating
- `evennia-plots` (game_systems) — plot threads and arcs with task checklists and bonuses

**RP cluster** — mechanics for RP-focused games; named with the `rp-` prefix to distinguish from PvE-leveling-loot systems
- [`evennia-rp-rules`](contribs/rpg/evennia_rp_rules/README.md) (rpg) — preview 0.1.0; value-neutral graded resolution, modifier pipeline, subjects, vocabulary and exact odds
- [`evennia-rp-chargen`](contribs/rpg/evennia_rp_chargen/README.md) (rpg) — preview 0.3.0; sheets, allocation, pips, catalog, loadouts, allowance/XP spending, build locks and change guards; depends on rules and links
- [`evennia-rp-contest`](contribs/rpg/evennia_rp_contest/README.md) (rpg) — preview 0.1.0; playable `+test` checks and player-led room challenges with private audits; depends on rules and links, with optional chargen, scenes and session integration
- `evennia-rp-combat` (rpg) — planned; turn-based combat tuned for PvP parity and narrative integration, using the rules kernel directly and its own resolver; never requires contest
- [`evennia-rp-equipment`](contribs/rpg/evennia_rp_equipment/README.md) (rpg) — preview 0.1.2; wearable gear anyone can make, with worn lines, provenance display and requirements on the wearer's build that grant nothing; worn gear holds the pips and abilities it needs through chargen's change guard; depends on rules and chargen
- [`evennia-rp-resources`](contribs/game_systems/evennia_rp_resources/README.md) (game_systems) — preview 0.1.3; passive resource accrual, atomic holdings, gathering leans, optional economy exchanges and reserved-stock refunds; depends only on links
- [`evennia-economy`](contribs/game_systems/evennia_economy/README.md) (game_systems) — preview 0.2.2; integer purses, passive income, atomic trades, reserved-stock stalls, fee boundaries and staff reconciliation; depends only on links
- `evennia-rp-party` (rpg) — party coordination for group combat
- [`evennia-rp-crafting`](contribs/game_systems/evennia_rp_crafting/README.md) (game_systems) — preview 0.2.0; invested Workshops, four cosmetic item behaviours, protected hallmarks, rate-limited EVENTs and staff review; depends on resources and links, with optional economy, equipment and accessibility
- `evennia-ooc-cosmetics` (game_systems) — out-of-character cosmetics driven by player nominations

The first three shipped RP packages (rules, chargen, contest) are a **contrib-native pilot**: their generic code
was authored here, wired into [`example_game`](example_game/README.md), and then
consumed by the source project through pinned dependencies and thin adapters.
Shared behavior and reusable integrations across all contribs are developed
here first; downstream games consume pinned public snapshots and own their
content, ruleset values, theme and composition. See
[CONTRIBUTING.md](CONTRIBUTING.md). The pilot does not establish production
readiness or several weeks of downstream use. Combat and party mechanics remain planned.

Clean package installation, populated upgrades and backup restores can be
verified with the [downstream snapshot gate](scripts/DOWNSTREAM.md).

## License

[BSD 3-Clause](LICENSE) — matches Evennia upstream so contribs can be submitted without license-alignment friction.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
