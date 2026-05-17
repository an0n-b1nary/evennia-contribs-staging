# Contributing

Thanks for your interest. This repo is a staging ground — its primary job is to surface friction *before* a contrib gets submitted upstream to [`evennia/evennia`](https://github.com/evennia/evennia), so the most valuable contribution is usually an honest install report.

## Trying a contrib in your game

1. Read the contrib's own `README.md` first. It lists dependencies, install steps, settings hooks, and any caveats.
2. Install via pip subdirectory (preferred):
   ```bash
   pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/<category>/<contrib_name>&egg=<contrib_name>"
   ```
3. If pip-from-subdirectory hits friction, copy the package directly into your game's local `contrib/` directory and document the version/commit you pulled from.
4. **Pin to a commit.** APIs may change between syncs. Don't track `main`.

## Filing a friction report

Open an issue in this repo, labeled with the contrib name (`accessibility`, `links`, `rptracker`, …).

The most useful issues describe one of:

- **API-shape friction** — "I had to monkey-patch X to make this work for my game." Each one is a contrib API bug; please include the patch you applied.
- **Doc bugs** — "The README said Y but I actually needed Z." Each one blocks upstream submission.
- **Install path bugs** — "pip install from subdirectory failed with this error." The install path is part of the contrib's public API surface.
- **Cross-contrib integration bugs** — "Installing contrib A broke contrib B." Especially important for contribs that use the soft-dependency pattern in [`evennia-links`](contribs/base_systems/).

Include:
- Contrib name and the commit SHA you installed from
- Your Evennia version
- Minimal reproduction or the failing traceback

## Submitting code

This repo is primarily a one-way extraction channel from upstream consumers, not a community fork. That said, if you have a clear bug fix:

1. Open an issue first to confirm the bug is in scope for the contrib (vs. specific to your game).
2. PRs are welcome for documentation fixes, typos, and small bug fixes against existing contribs.
3. Larger API changes should land in the source-of-truth project first and be re-extracted; please file an issue rather than opening a PR.

## Maintainer setup (anonymity guard)

This repo ships a pre-commit hook that refuses any commit containing references to the upstream private project the contribs are extracted from. The patterns live in a local-only `.anonymity-patterns` file (gitignored) so the public repo never reveals what is being blocked.

One-time setup per clone:

```bash
pip install pre-commit
pre-commit install
cp .anonymity-patterns.example .anonymity-patterns
# edit .anonymity-patterns with the actual names to block
```

Once installed, `git commit` will reject staged files containing any configured pattern. To test against the entire repo:

```bash
pre-commit run --all-files
```

If `.anonymity-patterns` is missing, the guard skips with a warning rather than failing — that way external contributors aren't blocked by maintainer-only config.

## Code style

This repo follows the [Evennia upstream code style](https://github.com/evennia/evennia/blob/main/CODING_STYLE.md) with one tooling difference: we use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting instead of Black + isort + Flake8. The rules are equivalent (100-char lines, Google-style docstrings, Evennia-conventional import order).

See [CODING_STYLE.md](CODING_STYLE.md) for the full conventions and the per-contrib `pyproject.toml` template.

Local setup (once per clone):

```bash
pip install pre-commit ruff
pre-commit install
```

Then `git commit` will run the anonymity guard, Ruff format, and Ruff check automatically.

## CI

Every push and PR runs two jobs:

- **lint** (~1 min): pre-commit (anonymity guard + Ruff format + Ruff check) + Python syntax check.
- **test** (~5–8 min per cell): Python 3.12 / 3.13 / 3.14 × ubuntu-latest. Installs Evennia, sets up a temporary game directory, installs every contrib via pip, runs each contrib's test suite via `evennia test`.

A PR can't merge until both jobs pass.

## License

By contributing, you agree your contributions are licensed under [BSD 3-Clause](LICENSE), matching Evennia upstream.
