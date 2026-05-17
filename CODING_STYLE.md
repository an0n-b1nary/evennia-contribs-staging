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

[tool.setuptools.packages.find]
include = ["evennia_<contrib_name>*"]
```

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
- **pre-commit** runs the anonymity guard, Ruff format, and Ruff check on every commit. One-time setup per clone:
  ```bash
  pip install pre-commit ruff
  pre-commit install
  ```
- **Manual format/lint:**
  ```bash
  ruff format .
  ruff check --fix .
  pre-commit run --all-files
  ```
- **GitHub Actions** runs the same checks in CI on every push and PR, plus the full test matrix (Python 3.12/3.13/3.14 against each contrib). See `.github/workflows/ci.yml`.
