# Contributing

Thanks for your interest. This repo is a staging ground — its primary job is to surface friction *before* a contrib gets submitted upstream to [`evennia/evennia`](https://github.com/evennia/evennia), so the most valuable contribution is usually an honest install report.

## Trying a contrib in your game

1. Read the contrib's own `README.md` first. It lists dependencies, install steps, settings hooks, and any caveats.
2. Install via pip subdirectory (preferred):
   ```bash
   pip install "evennia-<name> @ git+https://github.com/an0n-b1nary/evennia-contribs-staging.git@<full-sha>#subdirectory=contribs/<category>/<contrib_name>"
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

Shared contrib behavior and reusable integrations are developed here first.
Downstream games consume pinned public snapshots and own their content,
ruleset values, themes, and game composition.

1. Open an issue first to confirm the bug is in scope for the contrib (vs. specific to your game).
2. PRs are welcome for documentation fixes, typos, and small bug fixes against existing contribs.
3. Discuss larger API changes in an issue before implementation. Develop accepted changes in the owning contrib, with reference-game wiring and relevant seam tests.

Fixes need a regression test demonstrated to fail without the fix. Preserve
published migration history and verify populated-database upgrades alongside
fresh installation. Editable installs are for local development; deployment
and release verification use non-editable public snapshot pins.

## Maintainer setup (anonymity guards)

This repo ships five coordinated anonymity guards. All read from the same gitignored `.anonymity-patterns` file, so the public repo never reveals what is being blocked.

| Guard | Stage | Catches |
| --- | --- | --- |
| `anonymity-guard` | pre-commit | Forbidden strings in **file contents** of staged files. |
| `anonymity-identity-guard` | pre-commit | Forbidden strings in `git config user.name`/`user.email` or `GIT_{AUTHOR,COMMITTER}_*` env vars. |
| `file_issue.py` | before `gh` | Forbidden strings in an **issue title or body** you are about to publish. Not a hook — a wrapper you call instead of `gh issue create`. |
| `anonymity-issues.yml` | GitHub Actions | Forbidden strings in any issue or comment, however it was filed. Redacts, labels `anonymity-hold`, closes and locks; deletes an offending comment. |
| `anonymity-push-guard` | pre-push | Pushes to `github.com/<handle>/*` (where `<handle>` is `git config anonymity.expected-gh-account`) where any commit's author/committer matches a forbidden pattern, OR where the active `gh` account does not equal that handle. An active guard refuses protected pushes if patterns are missing, empty, unreadable, or invalid, or if Git cannot inspect commits. If the config key is unset, the guard is inactive — external clones and forks are unaffected by default. |

One-time setup per clone:

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push
cp .anonymity-patterns.example .anonymity-patterns
# edit .anonymity-patterns with the actual names to block (project names AND
# real-name identity patterns for the identity/push guards to use)

# Set the repo-local git identity to the anonymous account so commits never
# pick up your global identity:
git config user.name  "an0n-b1nary"
git config user.email "269072427+an0n-b1nary@users.noreply.github.com"

# Tell the push guard which gh account this clone is allowed to push as.
# Unset on external clones, so the push-time gh-account check no-ops there.
git config anonymity.expected-gh-account an0n-b1nary

# Before pushing, ensure the right gh account is active:
gh auth switch -u an0n-b1nary
```

To run the file-content + identity checks against the entire repo:

```bash
pre-commit run --all-files --hook-stage pre-commit
```

Verify the install with `git rev-parse --git-path hooks/pre-commit` and
`git rev-parse --git-path hooks/pre-push`. Both reported paths must contain
pre-commit-generated hook files (including the `--hook-type` for that stage).
Use Git's paths rather than assuming `.git` is a directory: linked worktrees
share the clone's hooks. The config also sets both default install hook types,
so a plain `pre-commit install` installs both stages.

The file-content and commit-identity hooks skip with a warning when patterns
are missing, allowing external contributors to commit without maintainer config.
The issue wrapper fails closed. The push guard is inactive when the expected
account is unset; once configured, protected pushes require valid, nonempty
patterns and a matching active account.

The push guard supports both native Git input and pre-commit's environment
variables. Pre-commit forwards only one ref's range for a multi-ref push, so
its guard also checks all local branch/tag commits absent from that remote's
tracking refs. A forbidden identity on another unpublished branch can therefore
block a push; correct that identity or remove the obsolete local branch before
retrying. Git inspection failures block the push instead of skipping commits.

### Issues are not covered by the pre-commit hooks

Nothing about an issue passes through git, so the pre-commit guards never see
one. File through the wrapper instead of `gh` directly:

```bash
python scripts/file_issue.py create --title "..." --body-file draft.md --label bug
python scripts/file_issue.py comment 7 --body-file reply.md

# Private targets require an explicit opt-in and verified GitHub visibility:
python scripts/file_issue.py comment 7 --repo owner/private-game --private --body-file reply.md

# scan without publishing:
python scripts/file_issue.py create --title "..." --body-file draft.md --dry-run
```

Unlike the pre-commit hook — which *skips* when `.anonymity-patterns` is absent,
so external clones are not blocked by config they were never given — the wrapper
**fails closed**. A missing patterns file at commit time means "not the
maintainer's clone"; at publish time it means "about to publish, with no idea
what is forbidden".

`--private` requires `--repo owner/name` and verifies that GitHub reports that
exact repository as private. Failed lookups, public targets, mismatched identities,
and missing patterns abort. Both fields are still scanned; matching lines are
printed as warnings for a verified private target. Use this mode only from a
private terminal. `--dry-run` performs the same visibility check and scan without
publishing. Without the explicit flag, the normal blocking scan applies to every
target, including private ones.

`.github/workflows/anonymity-issues.yml` sweeps every issue and comment
server-side, so the web UI and the API are covered too. Be clear about what that
buys: it runs after publication. GitHub emails watchers the original text on
submit and exposes it on the public events firehose, and no amount of editing
recalls either. The sweep closes the web-visible copy and raises an alarm; it
does not un-publish anything. The wrapper is the control that actually prevents.

The sweep never logs what it matched. Actions logs on a public repo are
world-readable, so printing the offending line — or even the pattern that caught
it — would republish the leak somewhere more durable than the issue. It reports
counts only.

## Code style

This repo follows the [Evennia upstream code style](https://github.com/evennia/evennia/blob/main/CODING_STYLE.md) with one tooling difference: we use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting instead of Black + isort + Flake8. The rules are equivalent (100-char lines, Google-style docstrings, Evennia-conventional import order).

See [CODING_STYLE.md](CODING_STYLE.md) for the full conventions and the per-contrib `pyproject.toml` template. Web-surface contribs also follow [UI_CONVENTIONS.md](UI_CONVENTIONS.md).

Host games adapting the sandbox shell can follow [WEB_PORTING.md](WEB_PORTING.md)
for navigation, homepage widgets, viewer policy, template checks, and live scenes.

Local setup (once per clone; the Ruff version matches the hook pin):

```bash
pip install pre-commit ruff==0.16.10
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Then `git commit` will run the anonymity guards, the template sweep, Ruff format, and Ruff check automatically, and `git push` will run the anonymity push guard.

## Template sweep

`scripts/check_templates.py` compiles every Django template in the repo and checks
markup conventions for web-surface contribs as well: no inline styles, namespaced
custom classes, scroll wrappers around tables, and empty branches for content loops.
It also fails on multi-line `{# ... #}` comments and templates that include or extend
themselves.

It exists because a broken template is invisible to a normal view test. Asserting on a
view's context compiles no template at all, so a page can be a guaranteed 500 while its
tests stay green — which is exactly how four such pages shipped here.

The sweep needs Django importable but nothing else: no settings module, no database, no
game directory. If Django is missing it prints a hint and passes, so a bare clone is not
blocked; CI runs it with `--require-django` in the test job, where Django is installed.

Note what it does *not* cover: compiling a template does not resolve `{% extends %}` or
`{% include %}` targets, run a single filter, or reverse a single URL. The sweep is a
floor, not a substitute for rendering.

## Render tests

**If your contrib ships web pages, every page needs at least one test that calls
`response.render()`.** A class-based view returns a lazy `TemplateResponse`, so a test
that asserts on `response.context_data` never touches the template — which is how four
guaranteed-500 pages shipped here under a green suite.

Every contrib that ships pages now does this — boards, calendar, jobs, lore, maps,
plots, regions, scenes and xp — and `evennia_accessibility` renders the three form
partials the others include. Copy whichever is closest to your contrib's shape.

The established pattern:

- Make the test module double as a **test URLconf**: declare `urlpatterns` at module
  level mounting your contrib's routes the way its `urls.py` documents, splatting in
  `evennia.web.urls.urlpatterns` after them — `website/base.html` reverses Evennia's own
  routes, and without them every render dies on an unrelated `NoReverseMatch`. Opt in
  per class with `@override_settings(ROOT_URLCONF=__name__)`.
- Drive views with `RequestFactory` and call them directly, not with Django's
  `TestClient`: the `TestClient` trips an Evennia template-context `RecursionError` on
  authenticated HTML pages.
- Attach a session — `request.session = import_module(settings.SESSION_ENGINE).SessionStore()`.
  Evennia's `general_context` processor reads `request.session["puppet"]` for any
  authenticated user, and `RequestFactory` attaches no session.
- Assert on rendered text, not just on a 200: an empty state's wording, a link that
  should be there, a link that should *not* be there for the wrong viewer.
- Outbound links to a soft-dependency contrib go through `{% url 'name' arg as var %}`,
  which assigns `""` on `NoReverseMatch` instead of raising. Test both halves: the
  degraded render under your own URLconf, and the linked render under a second URLconf
  that mounts stub partner routes.
- Include partials your own contrib ships, or ones from a package your `[web]` extra
  requires. Never reach into the host game's template tree (`website/partials/...`) —
  nothing puts those files there, and an `{% include %}` of a file that does not exist
  is invisible until the page renders.
- Render the *empty* state as well as the populated one. It is what a fresh install
  shows first, and it is usually the branch that includes a partial.

## CI

Every push and PR runs lint, the full contrib test matrix, and partner integration jobs:

- **lint** (~1 min): pre-commit (anonymity guard + Ruff format + Ruff check) + Python syntax check.
- **test** (~5–8 min per cell): Python 3.12 / 3.13 / 3.14 × ubuntu-latest. Installs Evennia, runs the template sweep, sets up a temporary game directory, installs every contrib via pip, runs each contrib's test suite via `evennia test`.

- **partners**: two fresh Python 3.12 environments, one with every contrib
  and one with calendar omitted from installation and app registration. Each
  runs the maps suite with host settings plus real overlay, URL, command-import,
  rendered static/live map, tile feed, and browsable API checks.

A PR can't merge until the required checks pass.

To reproduce the absent-calendar cell, use a **fresh** Python 3.12 venv with
`evennia==6.0.0` installed and its executables on PATH, from the repo root:

```bash
evennia --init ci_game < /dev/null
python scripts/ci_install_contribs.py ci_game --exclude evennia-calendar
(cd ci_game && evennia migrate --noinput < /dev/null)
python scripts/ci_run_partner_tests.py ci_game --calendar absent
```

In another fresh environment, omit `--exclude` and pass `--calendar present`.
The runner checks that an absent partner has no importable package or installed
distribution, and rejects launcher exits that ran zero tests. Exclusions also
fail before pip runs if a retained contrib has a hard dependency on the omitted
package. These games use test-only MD5 hashing and a small fixture rather than
the full sandbox seeder, which deliberately requires every demo contrib.

## Contrib release versions

When cutting a contrib version, update `pyproject.toml` and `__version__` in
`__init__.py` together, then move shipped notes into a dated changelog section
for that version. Keep future `## [Unreleased]` notes above released versions.
A new contrib may keep its initial notes under Unreleased until its first
release is ready.

Run `python scripts/check_contrib_versions.py` before committing. CI checks
all contribs without importing their Django apps, then repeats the check with
`--installed` after editable installation to verify distribution metadata.
Calendar and plots also compare their exported version to installed metadata
in their own suites, without hard-coding release numbers.

## License

By contributing, you agree your contributions are licensed under [BSD 3-Clause](LICENSE), matching Evennia upstream.

### Resource partner profiles

Use a fresh Python 3.12 environment for each profile, with Evennia 6.0.0. Create
an empty game with `evennia --init ci_game < /dev/null`, then run
`python scripts/ci_install_contribs.py ci_game --exclude evennia-maps` (or exclude
`evennia-plots`, `evennia-social`, `evennia-rptracker`, or `evennia-economy`). Migrate with
`evennia migrate --noinput < /dev/null` from the game. Run
`python scripts/ci_run_resources_tests.py ci_game --absent evennia_maps`
from the repo, substituting the excluded app label.
The runner verifies physical absence and requires a positive test count. Omit
installation exclusions for the present profile.

### Economy partner profiles

Repeat the fresh-environment procedure above, excluding `evennia-rp-resources`,
`evennia-jobs`, or `evennia-rp-equipment`, then run
`python scripts/ci_run_economy_tests.py ci_game --absent evennia_rp_resources`
(substitute the excluded app label). Omit exclusions and `--absent` for the
present profile. This runs the economy suite plus real resource exchange,
equipment refusal/sealing and staff-review job seams. The resources matrix
also checks an environment with economy genuinely unimportable.

The full contrib matrix has a 45-minute job limit; partner jobs have 30 minutes.
These bounds include installation/migration and allow the suite to grow across
the supported Python versions without cancelling normal progress.
