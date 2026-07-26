# AGENTS.md — evennia-contribs-staging

Guidance for coding agents working in this repo, including automated
pipeline agents executing extraction, integration, or verification tasks.

## What this is

Public staging mono-repo for Evennia contribs pre-upstream. Each contrib is
a pip-installable package under `contribs/<category>/<name>/`. `example_game/`
is a scaffolded Evennia 6.x game that installs and wires every contrib — the
reference integration and living sandbox.

**This repo is public and anonymity-guarded.** Never reference the private
source project, its repo, its domain, or its module layout — except in the
deliberately curated `MIGRATION_NOTES.md` prose. Public-facing terms: "the
source project", "an upstream MUSH game". The pre-commit anonymity guard
(`scripts/anonymity_guard.py`) enforces this on every commit, including
import-statement forms of source-tree paths (`from world.<app> …`), and it
must pass on every commit. `PLAN.md` is gitignored and must stay that way.

## Layout

- `contribs/{base_systems,game_systems,utils}/<name>/` — the packages, each
  with `pyproject.toml`, `README.md`, `CHANGELOG.md`, tests
- `example_game/` — integration game (Evennia scaffold, not a package);
  `server/conf/test_settings.py` is the integration-gate settings module
- `scripts/ci_install_contribs.py`, `scripts/ci_run_tests.py` — CI harness
  (install all contribs into a throwaway game, run every suite)
- `.pre-commit-config.yaml` — anonymity guards + ruff; repo-root
  `pyproject.toml` holds the shared ruff config

## Running checks

Use a Python 3.12 venv with `evennia>=6.0` and every contrib installed
editable (`pip install -e`, in dependency order — see the install loop in
`example_game/README.md`; `evennia_links` first, `evennia_posing` before
`evennia_social`).

- Lint + anonymity: `pre-commit run --all-files`
- Contrib suites (mirrors CI):
  `evennia --init /tmp/ci_game && python scripts/ci_install_contribs.py /tmp/ci_game && cd /tmp/ci_game && evennia migrate --noinput && evennia test --settings settings.py <app_label> [<app_label> …]`
- Sandbox integration gate:
  `cd example_game && evennia test --settings test_settings.py typeclasses commands world`

## Evennia invocation gotchas (hard-won — read before running anything)

- `--settings` takes a **bare filename** relative to
  `gamedir/server/conf/` (`settings.py`, `test_settings.py`). A dotted path
  (`server.conf.settings`) makes the launcher fail config import and **exit
  0 having run zero tests** — a silently-green run. Always confirm the
  `Ran N tests` line, never trust the exit code alone.
- Always redirect stdin: `evennia … < /dev/null`. First-run superuser
  creation blocks forever when stdin is a pipe.
- Full-suite runs take minutes and print progress as dots; a pause is not
  necessarily a hang. For unattended runs, launch detached
  (`setsid nohup … &`) and poll the log.
- `evennia migrate` on a fresh game dir needs `--noinput < /dev/null`.
- `EvenniaTest` creates two accounts per test — use settings with the fast
  MD5 hasher (throwaway games get it from `ci_install_contribs.py`;
  `example_game` has it in `test_settings.py`).

## Conventions

- Commit prefixes: `[evennia-<name>]` for per-contrib history
  (`git log --grep="\[evennia-links\]"`); `feat(example_game):`,
  `fix(ci):`, `docs:` conventional style elsewhere.
- Contrib code is extracted from the source project and synced by hand:
  substantive changes land in the source first and are mirrored here with a
  regression test (verified to fail without the fix); staging-originated
  fixes use `[evennia-<name>] fix:`.
- Model-bearing contribs: generate migrations, never hand-write; verify
  `makemigrations --check` is clean. Optional partners are integer
  soft-references + gated listeners (see `evennia_links`' README).
- Ruff runs via pre-commit (`ruff` + `ruff-format`); match the existing
  style rather than reformatting wholesale.
