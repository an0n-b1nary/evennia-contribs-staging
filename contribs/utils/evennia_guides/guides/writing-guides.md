---
key: writing-guides
title: Writing guide pages
audience: staff
category: Staff
summary: How guide pages are written, where they live, and how one is hidden until its system opens.
---
Every page in this guide is a Markdown file. Each file starts with a short block of settings between two `---` lines, then the text.

```
---
key: trading
title: Money & trade
category: Making & trading
requires: RP_ECONOMY_REVEALED
summary: How money comes in and how trades work.
---
Text of the page...
```

## Where pages live

Each installed contrib can ship pages in its own `guides/` folder, and the game adds its own folders in `GUIDES_DIRS`. If two pages share a key, the game's page wins. That's how a game rewrites a contrib's page in its own words.

Pages are read when the server starts, so a new or edited page appears after a reload.

## Hiding a page until its system opens

`requires:` names a check, usually a reveal switch such as `RP_ECONOMY_REVEALED`. Until the check passes, players can't see the page, and links to it show as plain text. Staff can still read it, with a note saying why players can't, so it can be proofread before the reveal. A name the game doesn't recognise keeps the page hidden.

`audience: staff` makes a page staff-only, like this one.

## Design insights and links

A **Design insight** explains why a system works as it does. It goes straight after the paragraph it comments on:

```
:::insight[Why nothing decays]{no-punishment-for-absence}
Stock you've earned stays yours while you're away.
:::
```

The part in `{...}` is optional and names one or more principle pages (`kind: principle`). The Design principles page lists every insight tagged with each principle.

`[[key]]` links to another page by its key, and `[[key|some words]]` sets the link text.

## Other kinds of page

- `kind: principle` is a design principle, listed on the Design principles page.
- `kind: term` is a glossary entry. Give it a `summary`: links to it show the summary when hovered.
- `footer: true` links the page from the bottom of every other page.

## Checking pages

`evennia guides_check` lists files that failed to load, links and principle tags that name no page, and `requires:` names the game doesn't recognise. Run it before a reload that adds pages.
