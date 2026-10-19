# Contributing

For lore/readable integration, run
`python scripts/ci_run_lore_item_tests.py ci_game/lore_items` in a fresh installed
environment. The `lore-items-partners` CI matrix also starts fresh environments
with either `evennia-rp-crafting` or `evennia-lore` actually excluded by
`ci_install_contribs.py --exclude`, then uses the matching `--absent` app label.
This exercises staff tomes without crafting and existing crafted metadata
without lore; changing only `INSTALLED_APPS` does not prove physical absence.

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

### Parallel PRs and release metadata

Before landing parallel work that touches the same contrib, choose a merge
order and integrate each predecessor into the next branch. Allocate versions
against that combined tree: two independent feature releases must not reuse
the same version or replace one another's changelog entries. Keep each release
under its own heading, and update `pyproject.toml` and `__version__` together.

Recheck sibling dependency ranges in both required dependencies and optional
extras after every version change. A consumer's upper bound may need updating
even when its own code did not change. Run `python scripts/check_contrib_versions.py`,
reinstall the affected packages, then run it with `--installed` and exercise
the reference-game seams. Rebuild the golden database from the combined
migrations and seed content rather than choosing either branch's binary file.

Keep the queued branches current if a predecessor changes. Merge each PR only
after CI passes on its final integrated revision; earlier green runs do not
validate subsequent conflict resolutions or metadata edits.

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

## Fast local test loop

Run tests from a throwaway game set up like CI's (`evennia --init`,
`python scripts/ci_install_contribs.py <game>`, then `evennia migrate`), or from
`example_game` with `--settings test_settings.py`. Both use the links test
runner, so a long run doesn't slow down as it goes.

- **Narrow labels:** `evennia test --settings settings.py evennia_x.tests.SomeClass`
  runs one class, and `…SomeClass.test_name` one test.
- **Parallel workers:** `--parallel auto` runs one worker per CPU, each with its
  own copy of the test database. Use it for anything larger than one contrib.
  The whole contrib suite takes about 5 minutes with 6 workers, against over 20
  serially.
- **Keep the test database:** every invocation spends most of a minute creating
  the test database and migrating every app. For repeat runs of a narrow label,
  point the test database at a file in a test-only settings module and pass
  `--keepdb`:

  ```python
  # <game>/server/conf/keepdb_settings.py
  import os
  from copy import deepcopy

  from server.conf.settings import *  # noqa: F403

  DATABASES = deepcopy(DATABASES)
  DATABASES["default"]["TEST"] = {"NAME": os.path.join(GAME_DIR, "server", "keepdb-test.sqlite3")}
  ```

  `evennia test --settings keepdb_settings.py --keepdb evennia_jobs` then took
  30 s on a repeat run, against 69 s without. Django applies new migrations to
  a kept database, but delete the file after switching to a branch whose
  migrations conflict. Don't combine `--keepdb` with `--parallel`: the workers'
  kept copies don't get new migrations. Race tests that skip on an in-memory
  database run against the file.
- **Profiling:** `--durations 20` lists the slowest tests.

## CI

Pushes to `main`, a nightly schedule and manual runs (**Run workflow** on the
Actions tab, for any branch) run every job. A PR runs less:

- **lint** (~1 min): pre-commit (anonymity guard + Ruff format + Ruff check) + Python syntax check. Always runs.
- **test** (~9 min per full cell): Python 3.12 / 3.13 / 3.14 × ubuntu-latest. Installs Evennia, runs the template sweep, sets up a temporary game directory, installs every contrib via pip, runs each contrib's test suite via `evennia test --parallel=auto`. On a PR only 3.12 runs the full suite; 3.13 and 3.14 run a smoke cell (install, migrate, syntax check, template sweep and the `evennia_links` suite with parallel workers), and run in full on `main` and nightly.
- **Partner jobs**, selected by `scripts/ci_scope.py` from the PR's changed
  files. A job runs when a changed contrib, or a contrib depending on it through
  hard dependencies or optional extras, is one the job installs, or when a file
  the job reads (its runner script, `example_game/`) changes. Top-level docs and
  lint-only files select none; any file the script doesn't classify selects
  every job. The `scope` job's log lists the choice and the reasons. Adding or
  renaming a partner job means updating `JOBS` in that script;
  `test_ci_scope.py` checks the two agree.

- **calendar-partners**: two fresh Python 3.12 environments, one with every contrib
  and one with calendar omitted from installation and app registration. Each
  runs the maps suite with host settings plus real overlay, URL, command-import,
  rendered static/live map, tile feed, and browsable API checks.
- **sandbox**: the `example_game` gate with every contrib installed. It and
  `live-playtest` run whenever any contrib or `example_game` changes.

The partner-profile jobs (`*-partners`, `rp-sandbox`, and the
`*-independent` jobs) each install one combination of partners in a fresh
environment. The sandbox gate, crafting, lore/items, and building and calendar
partner suites run with parallel workers; file-backed race runs stay serial.
Every test host uses the links test runner (`evennia_links.testing.TestRunner`),
which stops Evennia's test fixture from keeping each finished test's world in
memory.

The `test`, partner, `sandbox` and `live-playtest` jobs have a 30-minute
limit, the `*-independent` and `moderation-partners` jobs 20 minutes, and
lint and `scope` 5. These
bounds include installation and migration.

A skipped partner job reports as skipped, not failed. A failure in the nightly
run shows on the Actions tab and notifies whoever last changed the schedule.

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
It also checks every pin one contrib puts on another, in `dependencies` and in
optional extras alike, against the version declared here. CI never installs
the extras, so a stale extra pin would otherwise surface only for a game that
asks for it. A bump past a sibling's upper bound needs that pin widened, or the
bump made smaller.
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

When excluding resources, also exclude `evennia-rp-crafting`: resources is a
hard dependency of crafting, so retaining it would make the installer refuse.

### Crafting partner profiles

Use a fresh environment per profile, initialize `ci_game`, and install contribs
with `scripts/ci_install_contribs.py ci_game`, optionally excluding
`evennia-economy`, `evennia-rp-equipment`, or `evennia-accessibility`.
Run `python scripts/ci_run_crafting_tests.py ci_game/crafting_sandbox`, with
`--absent evennia_economy` (or the matching excluded app label). The destination
must be new. The runner copies reference-game code without databases or secrets,
checks physical absence, and runs the crafting suite and actual reference seams.
This includes Consumable deletion and retained provenance, Broadcast audience
limits, channel permissions and both mute controls. With accessibility absent,
Broadcast must remain in its user's room.
The accessibility-absent profile uses an empty URLconf because unrelated web
extras require accessibility; crafting's commands and items have no web surface.

### NPC partner profiles

Use a fresh environment per profile, initialize and migrate `ci_game`, and
install with `scripts/ci_install_contribs.py ci_game`. Optionally exclude
`evennia-scenes`, `evennia-plots`, or `evennia-rp-contest`, then run
`python scripts/ci_run_npc_tests.py ci_game --absent evennia_scenes`, substituting
the matching app label. The runner verifies physical absence, imports commands,
and exercises actual scene, plot and contest partners where installed.

The independent profile excludes scenes, plots, contest, posing, social,
rptracker, XP, chargen and equipment together. Only links and rules are hard
NPC dependencies. Consult the `npc-partners` CI matrix for the exact arguments.
The standard sandbox gate also exercises NPC MRO, reward exclusion, scene
privacy, session switching and idempotent seeding under all real partners.


### Combat without optional partners

Use a fresh Python 3.12 environment with `evennia==6.0.0`, links, rules and
combat installed in that order. Initialize a disposable Evennia game and
append those three contrib app labels to its `INSTALLED_APPS`. Run
`python scripts/ci_run_combat_tests.py <game> --absent evennia_rp_chargen
--absent evennia_npcs --absent evennia_scenes --absent evennia_posing
--absent evennia_social --absent evennia_accessibility`. Absence checks fail
if any named package remains importable. The CI combat-independent job then
adds real NPCs and repeats with the other partners still physically absent.
The full sandbox gate covers the installed-partner configuration and rendered
guide; `scripts/playtest.py run --suite combat --profile normal --no-browser`
checks ordinary authenticated player commands, including a Server reload.

### Party without optional partners

The `party-independent` CI job builds combat and Party wheels in a fresh
environment containing only Evennia, links and rules. Use an initialized,
migrated disposable game with those four contrib apps installed, then run
`python scripts/ci_run_party_tests.py <game>` with the same `--absent`
arguments above. The script requires physical package absence and a positive
test count. It writes only the disposable host's test settings and fixtures.

Run `--phase create` to save a populated fight and pending packet. Uninstall
Party, run `--phase absent --absent evennia_rp_party`, reinstall the built
wheel, then run `--phase restored`. Each phase starts a new process; it checks
retained Party data/build hashes, resolution without its modifiers, restored
old modifiers, unmodified packets created absent, and shelving. No live host
or production database belongs in this recipe. The full sandbox gate and
live combat suite also exercise Party with actual optional partners.
