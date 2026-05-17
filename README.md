# evennia-contribs-staging

A preview channel for [Evennia](https://www.evennia.com/) contribs in active development.

> ⚠️ This repository is a **preview channel for Evennia contribs in active development**. APIs may change. Migrations may be rewritten. Each contrib here is intended to eventually submit to [`evennia/evennia`](https://github.com/evennia/evennia) upstream. Use at your own risk; pin to specific commits if you depend on one.

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
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/<category>/<contrib_name>&egg=<contrib_name>"
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

## Planned contribs

The repo is being populated incrementally. The full anticipated slate, grouped by role:

**Foundation**
- `evennia-accessibility` (utils) — screen-reader helpers, accessible Django forms, MXP link conventions
- `evennia-links` (base_systems) — shared bridge-model base classes, edit-history & soft-delete mixins, optional notification dispatcher

**RP infrastructure** (each depends on `evennia-links`)
- `evennia-rp-social` (game_systems) — social foundation for RP games: ignore/mute, pose tracker, extended profiles, location discovery, instant teleport shortcuts, private messaging
- `evennia-regions` (game_systems) — geographic grouping of rooms with soft-archive and web views
- `evennia-rptracker` (game_systems) — pose tracking and RP session recording
- `evennia-jobs` (game_systems) — staff job-request workflow with anti-favoritism patterns
- `evennia-lore` (game_systems) — wiki-style knowledge entries with approval queue, version history, region-weighted passive discovery
- `evennia-xp` (game_systems) — pluggable XP collection with weekly payout
- `evennia-boards` (game_systems) — flat bulletin boards with subscriptions and post versioning
- `evennia-scenes` (game_systems) — scene logging with live entries, participants, web surface
- `evennia-calendar` (game_systems) — events, RSVP, optional cluster-lottery seating
- `evennia-plots` (game_systems) — plot threads and arcs with task checklists and bonuses

**RP cluster** — mechanics for RP-focused games; named with the `rp-` prefix to distinguish from PvE-leveling-loot systems
- `evennia-rp-chargen` (rpg) — stat allocation and ability selection; stats foundation for the rest of the cluster
- `evennia-rp-combat` (rpg) — turn-based combat tuned for PvP parity and narrative integration; pairs with Evennia's `rpg/traits`, `rpg/dice`, `rpg/buffs`
- `evennia-rp-contest` (rpg) — non-combat stat challenges using the same stat/roll system as rp-combat
- `evennia-rp-equipment` (rpg) — equipment slots with stat modifiers
- `evennia-rp-party` (rpg) — party coordination for group combat
- `evennia-rp-crafting` (game_systems) — IC crafting economy: resources, workshops, crafted items with cosmetic features, player-run storefronts
- `evennia-ooc-cosmetics` (game_systems) — out-of-character cosmetics driven by player nominations

Each contrib lands here only after it has run cleanly in its source project and at least one second downstream game for several weeks. APIs may change between extractions; pin to commits if you depend on one.

## License

[BSD 3-Clause](LICENSE) — matches Evennia upstream so contribs can be submitted without license-alignment friction.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
