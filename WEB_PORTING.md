# Porting the sandbox web structure into a host game

The sandbox's navigation, homepage, and viewer policy are game-directory code.
A host game can adapt them independently of installing the contrib packages.
Pin the reference revision: `30cc02b497b9876f5e4dea99a9396dd9d8c124d6` contains
the structural pass through mobile layouts. Installing a contrib alone does
not install this shell.

## Navigation and homepage

Use `example_game/web/website/nav.py` and `context_processors.py` as the starting
point. Register the processor in the host's template settings and adapt the
menu template to the resulting groups and account links. Record every landing
route in the table, including maps and regions. Keep the host's route names:
some contribs use namespaces and some use bare names. Reverse routes in Python
and omit unavailable destinations so one missing feature cannot break the shell.

Keep public, authenticated, and staff gates, and determine staff access with
the same predicate the destination views use. Test anonymous visitors, ordinary
accounts, builders, superusers, and intentionally conflicting Django flags.
Active links need tests on detail pages as well as list pages. Preserve keyboard
navigation, the skip link, landmarks, and the host's visual identity.

Adapt `example_game/web/website/views/index.py`, `website/index.html`, and the
homepage partials for the live-scene, upcoming-event, map, recent-activity, and
current-arc widgets. The installed-package inventory is specific to this demo.
Keep the owning views' visibility rules, documenting each queryset's origin.
An empty widget explains what will fill it. A missing optional app or route
degrades gracefully. Place game activity before engine information.

## Viewer policy and template conventions

The reference web staff policy is mirrored in the sandbox and contrib permission
modules. `EVENNIA_WEB_STAFF_PREDICATE` is an authoritative host hook;
`EVENNIA_WEB_STAFF_LOCK` defaults to `cmd:perm(Builder)`. Import failures and
predicate exceptions fail closed. Apply the policy to navigation and page
interiors together, preserving the destination's access checks.

Adapt [UI_CONVENTIONS.md](UI_CONVENTIONS.md) and `scripts/check_templates.py` to
the host template tree. Keep compilation, multi-line comment and self-inclusion
checks. The markup checks currently select contrib paths and namespaces;
explicitly retarget them for host templates instead of copying the selector
unchanged. Use the host's CSS prefix and existing theme. Preserve labelled
metadata, attribution wording, status text, separate staff controls, helpful
empty states, table overflow regions, and mobile cell labels.

Run the sweep in hooks and CI with `--require-django`. Add focused regressions
for rejected markup. Compile-only tests do not resolve includes or reverse URLs:
each affected view also needs `RequestFactory` tests calling `response.render()`
for populated and empty states.

## Readable live scenes

Use `evennia_scenes/views.py`, its reading partial and `live_scene.js`, API views,
and live-scene tests as the behavioral reference. Adapt imports, route names,
and host-specific model relationships rather than replacing files wholesale.

Keep the finished archive and live list separate. Live details default to the
latest log page and show status and participants. Polling rechecks access on
every request, returns safely rendered content, and stops when the scene closes
or access fails. A manual reload works without JavaScript. Keep private
responses out of shared caches.

Retain the existing fail-closed privacy predicate: public and pose-private tiers
are readable; other tiers require the existing invitation or staff policy.
Unknown tiers and archived scenes must stay protected. The authenticated API
keeps its archive default and permits explicit live status filtering and live
detail/log retrieval only for its existing readable privacy tiers.

Link the homepage and active map overlays to the same permitted destinations.
Cover private content, changed privacy, revoked invitations, deleted and OOC
entries, pagination, missing partner routes, and scene closure. Verify desktop
and mobile page widths and the no-JavaScript path with an isolated fixture game.

## Tracking private host work

Keep source-specific paths, findings, and issue links in the host repository.
Use `scripts/file_issue.py --private` on the create/comment subcommand with an
explicit `--repo owner/name` for a verified private target. The wrapper still
reports pattern hits and fails if visibility or patterns cannot be verified.
Public issues and commits retain the normal anonymity checks.
