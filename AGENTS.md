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

Use a Python 3.12 venv with `evennia==6.0.0` (pinned to the source project's
runtime — CI installs the same; the contrib packages themselves declare the
wider `evennia>=6.0`) and every contrib installed
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

## Landing a new contrib — wiring `example_game` is part of the job

**An extraction is not finished when the package is written and its own suite
passes. It is finished when `example_game` installs and exercises it.** Treat
the sandbox wiring as a required phase of every extraction, not a follow-up.

Three classes of defect are invisible to a contrib's own tests and only appear
in a game that loads everything together:

- **Install-order and app-registry faults** — `INSTALLED_APPS` ordering,
  `AppConfig.ready()` gating against partners that really are (or really
  aren't) installed, `AppRegistryNotReady` from an eager model import.
- **Seams under real partners** — a settings registry, signal collector, or
  soft-reference cleanup hook can be unit-tested with a stub on both ends and
  still be wrong. The sandbox is the only place the actual partner packages
  are present, which is the whole point of a seam.
- **Web wiring** — URL includes and namespaces, cross-contrib `{% url %}`
  reverses, template inheritance from `website/base.html`, static discovery,
  DRF router mounting. A `TemplateResponse` is lazy, so view tests asserting
  `status_code` or `context_data` never render the template and never see a
  `NoReverseMatch`.

Minimum wiring checklist: dependency-ordered `pip install -e`;
`INSTALLED_APPS` + a `####`-bannered settings block; commands registered in
`commands/default_cmdsets.py`; any typeclass mixin with its MRO-ordering note;
URL + API mounting if the contrib ships a web surface; `seed_sandbox` content
so the feature is visible rather than an empty page; a seam test in
`world/sandbox/tests.py`; `example_game/README.md` updated; golden DB
re-snapshotted after `evennia migrate`.

Easy to forget and worth doing every time: **uninstall an optional partner,
restart, and confirm the feature degrades instead of breaking.** Gated
`ready()` blocks and settings seams exist for exactly the absent-partner case,
and no suite here runs it.

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
