# Web UI conventions

This repository keeps each contrib self-contained. A web contrib may not rely on
the host game's CSS, design tokens, template partials, or custom template tags.
Presentation rules are mirrored in each contrib and checked by
`scripts/check_templates.py`.

## Content and metadata

- Detail metadata uses a labelled definition list (`<dl>`, `<dt>`, `<dd>`). Every
  value has a visible or screen-reader label.
- Use `Not recorded` when a scalar value is absent and `Unattributed` when an
  author or creator is absent. A real system attribution remains `System`.
- Statuses are Bootstrap 4 badges with text. Colour is supplemental and never
  the only status signal.
- Player actions and staff actions appear in separate action groups. Staff-only
  controls remain protected by the view's existing permission checks.
- Empty states say what belongs in the collection and name the in-game command
  or web action that creates it when one exists.
- Player-facing pages do not print database primary keys or dbrefs. Public
  sequence numbers and revision numbers are descriptive content and may remain.

## Markup and CSS

- Use Bootstrap 4.6 classes for generic layout and controls.
- Contrib-specific classes are namespaced `evennia-<contrib>-*`.
- Put all contrib rules in `static/evennia_<contrib>/css/evennia_<contrib>.css`.
  Do not use inline `style=` attributes or embedded `<style>` blocks.
- Every data table is inside an `evennia-<contrib>-table-scroll` region with a
  useful accessible label and keyboard focus. The region owns horizontal
  overflow so a narrow viewport does not make the page wider.
- Below 640px, data tables use stacked rows with a visible label in every cell.
  Mirror the `evennia-<contrib>-table-stack` rules in each contrib's stylesheet.
  Keep the column headers visually hidden rather than removing them and retain
  explicit table/rowgroup/row/cell roles when CSS changes their display. Mobile
  labels carry `aria-hidden="true"` so assistive technology uses the original
  headers. Full-width empty-state cells do not need a label.
- The calendar's automatic display uses a chronological list on narrow screens
  and a month grid on larger screens. Explicit grid/list controls preserve the
  selected month and work without JavaScript.

## Templates and tests

- Use `{% comment %}...{% endcomment %}` for multi-line template comments.
- A content loop has an `{% empty %}` branch or includes the contrib's empty
  state in that branch. An enclosing `{% if collection %}` with an `{% else %}`
  empty state also qualifies. The sweep checks all collections, including related
  managers and filtered or reversed lists. Structural collections (pagination,
  form fields, SVG geometry, and similar markup scaffolding) are explicitly
  excluded in `STRUCTURAL_LOOP_CONTEXTS`; iterator variable names are not exemptions.
- Web tests use `RequestFactory`, a module-level URLconf, and `response.render()`.
  They assert rendered text for both populated and empty states.
- New templates and CSS must be included by the package-data globs and verified
  in a built wheel; editable installs do not catch missing package data.
