# Migration notes — evennia-guides

This preview package is contrib-native: it was written here, not extracted
from a running game. It ships no game content except one staff page about
writing pages.

## First adoption

Install `evennia-guides` and add `evennia_guides` to `INSTALLED_APPS`. There
are no models, so there's nothing to migrate. Mount `evennia_guides.urls`,
point `GUIDES_DIRS` at the game's page directories, and run
`evennia guides_check`.

Pages that already exist as templates or flat pages can move over one at a
time: copy the text into a Markdown file with a `key` and `title`, then
replace the old route with a redirect to `/guide/<key>/`.

## 0.1.0

The first release.
