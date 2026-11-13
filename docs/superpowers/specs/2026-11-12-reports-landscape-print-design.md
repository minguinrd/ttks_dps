# Design: Landscape Print for the Reports Page (ttks_dps)

Date: 2026-11-12
Status: approved in conversation (short design; no builder check)
Size: small change — CSS/template tweaks plus one test

## Intent and why

The Reports page prints to portrait A4 (`@page { size: A4 }` in
`app/static/css/print.css`), where the 9-column ticket table is cramped across
21 cm and rows can even collapse into the phone "stacked" layout (those
`main.css` rules are not `screen`-scoped, so a narrow print viewport can match
them). Staff want the report to come out on landscape paper and fit it.

## Goals

- Reports print/PDF output uses A4 **landscape** and fits: all 9 table columns
  readable, summary/breakdown cards compact and intact
- Ticket-detail printing keeps its current portrait behaviour
- Printed tables are always real tables (never the phone stacked layout)

## Non-goals

- No changes to report data, filters, routes, or role gates
- No server-side PDF tooling; still `window.print()`
- No print-only header line with active filters/timestamp (declined for now)
- No new i18n strings

## Constraints

- `print.css` is shared with `tickets/detail.html` — landscape must be scoped
  to the reports document, not the global `@page` rule
- Existing tests must keep passing (`test_print_css_linked`,
  `test_print_button_present`, `test_detail_print_hides_forms`, i18n checks)

## Approaches considered

1. **Page-scoped `@page` via a head block** — chosen: add an empty
   `{% block page_css %}{% endblock %}` in `base.html` `<head>` after the
   `print.css` link; `reports/index.html` fills it with
   `@page { size: A4 landscape; margin: 1.5cm }`. Per-document override, no
   impact on ticket detail, no new stylesheet.
2. **Landscape globally in `print.css`** — rejected: ticket detail is a
   single-ticket document that wastes paper in landscape.
3. **Named pages (`@page` + `page:` property)** — rejected: browser support
   is uneven; a head block is universally reliable.

## Decisions (the how)

- **`base.html`:** new `{% block page_css %}{% endblock %}` at the end of
  `<head>` (after the `print.css` `<link>`), so page-level `@page` rules win
  the cascade
- **`reports/index.html`:** `{% block page_css %}` containing
  `@page { size: A4 landscape; margin: 1.5cm }`
- **`print.css` (inside `@media print`):**
  - stat cards (`.printable .row .card` summary block): no shadow, compact
    padding, smaller count type, `break-inside: avoid`
  - breakdown cards: `break-inside: avoid`
  - ticket table: ~9 pt type, reduced `td`/`th` padding, `table-layout` left
    auto, subject cell wraps (no forced nowrap)
  - keep existing rules: `thead { display: table-header-group }`,
    `tr { page-break-inside: avoid }`, chrome hiding, 10pt body
- **`main.css`:** change the phone stacked-table block to
  `@media screen and (max-width: 767.98px)` so print always renders a real
  table (the block's own comment already says it is for phones)
- **Test:** in `tests/test_reports.py`, assert the rendered reports page
  contains `size: A4 landscape`; ticket-detail page must **not**

## What's left to the builder

Implement the four file changes above, add the test, run
`.venv/bin/pytest -q` and `.venv/bin/ruff check .` (ruff only if Python
changes; expected to be untouched).
