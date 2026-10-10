# evennia-guides

> **Preview (0.1.0, Pre-Alpha).** This package was written directly as a
> contrib, and its API may move. Pin an exact commit.

Player guides for [Evennia](https://www.evennia.com) games, written as
Markdown files and served as web pages. It provides:

- **one Markdown file per page,** with a short front matter block for its key,
  title, category and audience;
- **Design insight** sidebars that explain why a system works as it does,
  placed beside the paragraph they comment on;
- **links between pages** by key, which turn into plain text when the target
  page is hidden, so a link never gives a hidden page away;
- **pages hidden until a check passes,** typically a reveal switch, so a
  system's guide can be written and proofread before players can see it;
- **staff pages** that only staff can read;
- a **Design principles** page that gathers every insight tagged with each
  principle, and a **glossary**;
- an **"Ask about this page"** link that opens a prefilled request form
  (`evennia-jobs` 0.3 or later, or any URL you choose).

Pages are separate from in-game `help`. The Markdown stays plain enough to
turn into help files later.

Contribs can ship their own pages, and a game can replace any of them with
its own version.

---

## Writing a page

```markdown
---
key: trading
title: Money & trade
category: Making & trading
requires: RP_ECONOMY_REVEALED
principles: [no-quota]
summary: How money comes in and how trades work.
---
Coins arrive on their own while you play.

:::insight[Why nothing decays]{no-quota}
Stock you've earned stays yours while you're away.
:::

See [[crafting]] for what to spend it on, or [[glossary-coin|coin]].

## Trading

Both sides change hands together, or neither does.
```

| Field | Meaning |
|---|---|
| `key` | Required. The page's URL and link key: `a-z`, `0-9`, `-`, `_`. `principles` and `glossary` are reserved. |
| `title` | Required. |
| `kind` | `guide` (default), `principle` (listed on the Design principles page) or `term` (listed in the glossary). |
| `category` | Groups guide pages on the index. Default `General`. |
| `audience` | `player` (default) or `staff`. |
| `requires` | A check name, or a list of them; all must pass for players to see the page. |
| `aliases` | Other keys that find the page. |
| `principles` | Principle pages this page illustrates. |
| `summary` | One line, shown on the index and when a link to the page is hovered. |
| `order` | Sort order within a category (default 100). |
| `footer` | `true` links the page from the bottom of every other page (a note about numbers, say). |

The body is [CommonMark](https://commonmark.org) with tables, plus:

- `:::insight[Title]{principle, ...}` … `:::` for a Design insight. The
  `{...}` tags are optional. Insights don't nest, and the `:::` lines start
  at the left margin.
- `[[key]]` or `[[key|link text]]` for a link to another page.
- A top-level `## Heading` starts a section. Pages with three or more get an
  "On this page" list.

Raw HTML is shown as text, never passed through.

On the web an insight is an `<aside>` labelled "Design insight: Title". It
stays in reading order, straight after its paragraph, so a screen reader
reaches it where a sighted reader would glance at it. On wide screens it
floats beside the text; on narrow ones it sits inline.

## Where pages come from

1. The `guides/` directory of every installed app, in `INSTALLED_APPS` order.
   A contrib that ships pages lists `guides/*.md` in its package data.
2. Each directory in `GUIDES_DIRS`, in order.

A later page with a key that's already loaded replaces the earlier one. Pages
are read once per process, so new or edited pages appear after a reload. A
file that fails to load is logged and skipped rather than taking the guide
down.

This package ships one staff page, `writing-guides`, a short guide to
writing pages for whoever writes them.

## Checks

`requires:` names a check. Checks are global, not per reader, and they're
read on every request, so a page appears as soon as its check passes. A name
resolves, first match wins, to:

1. `GUIDES_CHECKS[name]` in your settings: a bool, a callable, or a dotted
   path to a callable;
2. a check registered in code with `evennia_guides.checks.register_check(name, func)`;
3. an [`evennia-links`](../../base_systems/evennia_links/README.md) runtime
   setting of that name, when links is installed (such as
   `RP_ECONOMY_REVEALED`, which staff can change at runtime);
4. a Django setting of that name.

An unknown name, or a check that raises, keeps the page hidden.

## Who sees what

| Reader | Sees |
|---|---|
| Anyone, logged in or not | player pages whose checks pass |
| Staff (`GUIDES_STAFF_LOCK`) | every page, with hidden ones marked and the reason given |

A page a reader can't see is a 404, the same as one that doesn't exist.

## Install

```bash
pip install -e contribs/utils/evennia_guides
```

```python
# settings.py
INSTALLED_APPS += ["evennia_guides"]
GUIDES_DIRS = [os.path.join(GAME_DIR, "world", "guides")]
```

```python
# web/website/urls.py
path("guide/", include("evennia_guides.urls")),
```

The namespace comes from the package's `app_name`, so a bare include is
right. Routes: `evennia_guides:guide-index`, `guide-principles`,
`guide-glossary` and `guide-page` (one `key` argument). The templates extend
`website/base.html`.

## Settings

| Setting | Default | |
|---|---|---|
| `GUIDES_DIRS` | `()` | Host directories of pages, read after the apps' `guides/`. |
| `GUIDES_CHECKS` | `{}` | Check overrides: `{name: bool \| callable \| "dotted.path"}`. |
| `GUIDES_STAFF_LOCK` | `"perm(Admin)"` | Lock string for staff readers. |
| `GUIDES_ASK_URL` | `"job-create"` | Route name or literal URL for "Ask about this page". Falsy hides the link, and so does a route that doesn't reverse. |
| `GUIDES_ASK_URL_KWARGS` | `{"job_type": "request"}` | Arguments for reversing that route. |

The ask link adds `title` and `description` query parameters naming the page.
`evennia-jobs` 0.3 or later uses them to prefill its request form.

## Checking pages

```bash
evennia guides_check
```

This lists files that failed to load, links and principle tags that name no
page, checks that resolve to nothing, colliding aliases, and pages replaced
by later ones. It exits non-zero when there are errors, so it can run before
a deploy.

## Dependencies

`evennia>=6.0` and `markdown-it-py` (CommonMark, raw HTML off). Front matter
is read with PyYAML, which Evennia already requires.
