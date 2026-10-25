# Coding style

This repo follows [Evennia upstream's `CODING_STYLE.md`](https://github.com/evennia/evennia/blob/main/CODING_STYLE.md) with one tooling difference: we use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting instead of Black + isort + Flake8. The rules are equivalent (100-char lines, Google-style docstrings, Evennia-conventional import order).

When upstream and this doc disagree on substance (not tooling), upstream wins — the goal is that any contrib here can be `git mv`'d into `evennia/contrib/` without re-formatting.

## Code style

- **Python version:** 3.12+ syntax. Target the lowest Evennia supports (currently 3.12).
- **Line length:** 100 characters.
- **Indentation:** 4 spaces, no tabs.
- **Line endings:** LF (Unix). `.gitattributes` enforces this — Windows clones will see CRLF locally but Git stores LF.
- **Naming:**
  - `CamelCase` for classes
  - `snake_case` for functions, methods, variables
  - `ALL_CAPS` for module-level constants
- **Import order** (Ruff's `I` rule group enforces this automatically): stdlib → third-party (Twisted, Django, DRF) → Evennia lib → Evennia contrib → local (this contrib's modules).
- **License header** on every `.py` file:
  ```python
  # SPDX-License-Identifier: BSD-3-Clause
  # Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
  ```

## Docstrings

Google-style, required for all modules, classes, public functions, and public methods.

```python
def plain_list(rows, headers=None):
    """Format `rows` as a plain-text list suited for screen readers.

    Args:
        rows: Iterable of row sequences to render.
        headers: Optional iterable of column labels. If supplied, each row
            is rendered as "label: value" comma-joined pairs.

    Returns:
        str: One row per line, em-dash-joined when no headers are given.

    Notes:
        Designed for terminals where ANSI tables collapse poorly.
    """
```

Type hints in signatures are **encouraged but not required** for public functions and not required at all for internal helpers. Add them when they clarify intent, not to satisfy a tool.

## Tests

- **Default location:** `tests.py` at the contrib root (matches Evennia upstream).
- **Larger contribs** (more than ~500 lines of test code) may use a `tests/` directory with `tests/test_*.py` modules. Document the choice in the contrib's `MIGRATION_NOTES.md`.
- **Base class:** inherit from `evennia.utils.test_resources.EvenniaTest`.
- **Mocks:** use `unittest.mock`; prefer narrow patches over wholesale fakes.
- Tests must pass under `EvenniaTest` with no source-project-local fixtures (per Evennia's standard contrib requirements).

## Command syntax

No command is harder to type than `+command/switch target=value`. Players
come from MUSH and MUX clients: they read `/` as one switch and `=` as "this,
to that", and some clients treat `;` as a line break. When an operation needs
more than that, add a command or a step instead of more syntax.

These rules cover every contrib-defined command, including replacements of
Evennia commands. Stock commands that no contrib replaces retain Evennia's
behavior. Use `evennia_links.command_syntax.StrictSwitchMixin` before an
Evennia command base and declare `switch_options` (empty for no switches).
Refuse unknown, ambiguous or stacked switches before any lookup or mutation.

1. **One switch at most.** Never `+build/resident/add`. A modifier becomes a
   switch of its own (`+resident/add`), a companion command (`+thread` beside
   `+plot`), or an armed flag (rule 3).
2. **A choice among a few values may be the switch:** `+attack/penetrating`.
   Declare `switch_options` so MuxCommand accepts any unique prefix
   (`+attack/p`), and reject a second switch with a usage message.
3. **Other modifiers are their own commands.** `+empower`, then `+attack`.
   The flag arms the next action, shows in the status display, clears when
   that action resolves (a cancelled action keeps it), and `+empower/off`
   disarms it.
4. **No `;`, `~` or `|` separators, and no `:` sub-fields.** A
   one-character prefix alias, like `;` for `semipose`, is not a separator
   and is fine.
5. **`=` relates one target to one value.** The pattern is `target=value`, and
   it follows `give`: `thing=recipient`, `record=value`. With no target, the
   value is bare (`+craft/desc <text>`, not `+craft/desc = <text>`).
   - **A target is one thing:** a name, `#N`, or one address step. `#N.M` is
     a record within a record, such as a plot thread or a revision
     (`+jobs/approve 12.3`). `thing/field` is a member or field
     (`+bb board/post`, `+npc/stat Guard/strength=3`).
   - **Never a run of positional arguments** like `<project> <room> <x>=`. Take
     the context from where the player stands, or add a step.
   - **The value is one thing,** optionally with one address step
     (`=<move>/<domain>`).
6. **Commas list like items only:** several targets, recipients or ranked
   choices. They never stack options (`=<move>,burst,empower`) or attach a
   note (`=<amount>,<note>`).
7. **Amounts read like `give`:** `53 scales`, `2 timber`.
8. **A reason or comment may trail the line after ` # `:**
   `+xp/grant Ana=5 # ran the tournament`. The `#` needs whitespace on both
   sides, so `#12` and `#N.M` still parse as references.
9. **No JSON on the command line.** Set one field per command
   (`+tactics/set Careful/appetite=cautious`). If validation spans several
   fields, use a draft: `/new`, a switch per field, then `/finish` and
   `/cancel`, as `+craft` and `+tome` do. Staff-only `+runtime` is exempt.
10. **Guards belong in a confirmation token, not in what the player types.**
    Expected owners, versions, fingerprints and agreement wording go there.
    The first call previews and prints a token, and repeating it with
    `=<token>` commits, as `+build/discard` does.
11. **Acting as an NPC is puppet state, not syntax.** After `+npc/puppet`,
    the ordinary commands act as the NPC, and every message says who you are
    puppeting. There are no `/npc` or `/as` switches.

`scripts/check_command_syntax.py` enforces what can be read from source:
- stacked switches in help, guides, READMEs and templates
- forbidden separators, nested `=`, JSON, `[,option]` stacking and positional
  runs in help usage lines
- input split on `;`

It runs in pre-commit and CI. Offenders that predate this section are listed in
`scripts/command_syntax_allowlist.txt`. A PR that fixes a contrib deletes that
contrib's lines; an entry that matches nothing fails the sweep, so the list only
shrinks. Do not add lines to land new syntax.

## Web UI

Contribs that ship templates follow the shared [UI conventions](UI_CONVENTIONS.md)
for metadata, empty states, accessibility, CSS ownership, and rendered-page tests.

## Per-contrib packaging

Every contrib directory needs a minimal `pyproject.toml` so `pip install -e "git+...#subdirectory=..."` works. Template:

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "evennia-<contrib-name>"
version = "0.1.0"
description = "<one-line purpose>"
readme = "README.md"
license = { text = "BSD-3-Clause" }
authors = [{ name = "an0n-b1nary" }]
requires-python = ">=3.12"
classifiers = [
    "Development Status :: 3 - Alpha",
    "Framework :: Django",
    "License :: OSI Approved :: BSD License",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
dependencies = ["evennia>=6.0"]

[project.optional-dependencies]
test = ["pytest>=8.0"]

# Flat layout: package contents (`__init__.py`, `models.py`, etc.) live at the
# same level as this pyproject.toml — NOT in a nested `evennia_<contrib_name>/`
# subdirectory. The package-dir mapping below tells setuptools that the
# `evennia_<contrib_name>` import name resolves to the current directory.
# This mirrors Evennia upstream's per-contrib layout so an upstream submission
# is a path-only `git mv contribs/<cat>/<name>/* evennia/contrib/<cat>/<name>/`.
[tool.setuptools]
packages = ["evennia_<contrib_name>"]

[tool.setuptools.package-dir]
"evennia_<contrib_name>" = "."

# Ship non-Python files (templates, static, fixtures) with the wheel. Adjust
# the globs per contrib — omit a line if the contrib has no such files.
[tool.setuptools.package-data]
evennia_<contrib_name> = [
    "templates/evennia_<contrib_name>/*.html",
    "static/evennia_<contrib_name>/css/*.css",
]
```

**Why flat?** Setuptools' default `[tool.setuptools.packages.find]` expects a nested layout (`pyproject.toml` at `foo/`, package at `foo/foo/__init__.py`). Our contribs are flat — the `__init__.py` is *next to* the pyproject.toml. Without the `package-dir` mapping the package fails to install (silently — `pip install -e` reports success but `import` fails). If you see `ModuleNotFoundError: No module named 'evennia_<contrib_name>'` right after a clean install, this is the cause.

### `apps.py` (Django app registration)

Every contrib needs an `apps.py` so the package is recognized as a Django app when added to `INSTALLED_APPS`. Even a pure-utility contrib (no models, no signals) needs one if it ships templates or static files, so Django's finders pick them up.

```python
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.

from django.apps import AppConfig


class Evennia<ContribName>Config(AppConfig):
    name = "evennia_<contrib_name>"
    default_auto_field = "django.db.models.BigAutoField"
```

Add a `ready()` method only when the contrib has soft-dependency wiring to do (the cross-contrib bridge pattern — gate model/listener registration behind `INSTALLED_APPS` checks):

```python
    def ready(self):
        from django.conf import settings
        if "evennia_scenes" in settings.INSTALLED_APPS:
            from . import bridges_scenes  # noqa: F401
```

Keep `ready()` minimal: import-only, no heavy work; Django calls it at startup.

### Dependencies between contribs

- **Hard dependencies** on other staging-repo contribs go in `dependencies`, using the git-subdirectory pip syntax:
  ```toml
  dependencies = [
      "evennia>=6.0",
      "evennia-links @ git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/base_systems/evennia_links",
  ]
  ```
- **Soft dependencies** (gated at runtime via `apps.py.ready()` per the cross-contrib bridge pattern) are **not** listed in `dependencies`. The contrib must function with the soft-dependency absent.

## Tooling

- **Ruff** handles formatting, linting, and import sorting. Config lives at the repo root in `pyproject.toml` under `[tool.ruff]`. Same 100-char limit as Evennia upstream's Black; same rule set as upstream's Flake8 (and a few extras: bugbear, pyupgrade, simplify).
- **pre-commit** runs the anonymity guard, the template and command syntax sweeps, Ruff format, and Ruff check on every commit. One-time setup per clone:
  ```bash
  pip install pre-commit ruff==0.16.10
  pre-commit install --hook-type pre-commit --hook-type pre-push
  ```
- Verify both hooks with `git rev-parse --git-path hooks/pre-commit` and
  `git rev-parse --git-path hooks/pre-push`; both reported paths must contain
  pre-commit-generated hook files. This also works in linked worktrees.
- **Manual format/lint:**
  ```bash
  ruff format .
  ruff check --fix .
  pre-commit run --all-files
  ```
- **GitHub Actions** runs the same checks in CI on every push and PR, plus the full test matrix (Python 3.12/3.13/3.14 against each contrib). See `.github/workflows/ci.yml`.
