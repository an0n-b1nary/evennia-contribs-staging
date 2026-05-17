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

## License

[BSD 3-Clause](LICENSE) — matches Evennia upstream so contribs can be submitted without license-alignment friction.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
