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

## Staff pages

A contrib's staff page explains its staff tools in general terms, for any game that installs it. Give it the key `<contrib>-staff`, `audience: staff` and `category: Staff`, and no `requires:`: staff can read every page anyway. Lay it out in this order:

1. **What it's for:** a sentence or two on what staff use the system's tools for.
2. **Tasks and commands:** grouped by the job, not a full command list. `help <command>` has the full usage.
3. **What's safe to change:** what staff may edit, and what never to edit by hand, such as permanent keys or history.
4. **Privacy:** what players can hide, what staff can see, and why it stays with staff.
5. **Review jobs:** which jobs the system files, and how to answer them.

The same link rule applies as for player pages, and the numbers stay in broad strokes. A game links its contribs' staff pages from its own staff index.

## Other kinds of page

- `kind: principle` is a design principle, listed on the Design principles page.
- `kind: term` is a glossary entry. Give it a `summary`: links to it show the summary when hovered.
- `footer: true` links the page from the bottom of every other page.

## Checking pages

`evennia guides_check` lists files that failed to load, links and principle tags that name no page, and `requires:` names the game doesn't recognise. Run it before a reload that adds pages.
