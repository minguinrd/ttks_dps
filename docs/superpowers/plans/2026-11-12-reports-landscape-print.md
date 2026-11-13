# Reports Landscape Print Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Reports page prints/PDFs to A4 landscape and fits it — compact cards, a tight 9-column table — while ticket-detail printing stays portrait.

**Architecture:** A page-scoped `{% block page_css %}` in `base.html`'s `<head>` (after the `print.css` link, so later `@page` rules win the cascade) carries the reports page's `@page { size: A4 landscape }` override; `print.css` gains compact `@media print` rules for the report's cards and table; the phone stacked-table block in `main.css` becomes `screen`-scoped so print always renders a real table.

**Tech Stack:** Existing stack — Jinja2 templates, plain CSS, pytest. **No new dependencies, no Python changes beyond tests.**

**Spec:** `docs/superpowers/specs/2026-11-12-reports-landscape-print-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Landscape must be scoped to the reports document only: `print.css` keeps its global `@page { size: A4; margin: 1.5cm }` (portrait) for `tickets/detail.html`
- `print.css` stays `@media print`-only rules; the `page_css` block in `base.html` must sit **after** the `print.css` `<link>` (end of `<head>`) so the override wins the cascade
- No new i18n strings, no new user-visible literals (CSS/HTML comments are fine — nothing to translate)
- Reports route/role gates (`role_required("agent", "admin")`) untouched; no route or form changes
- Existing tests must keep passing: `test_print_css_linked`, `test_print_button_present`, `test_detail_print_hides_forms`, i18n completeness
- Every task ends green: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` (if format check fails, run `.venv/bin/ruff format .` then re-check)
- Commit each task separately

## Review Focus

1. **Landscape rule missing from the rendered reports page** (block not filled or misspelled) → Task 1 `test_reports_page_declares_landscape_page` asserts `"size: A4 landscape"` in the `/reports` HTML
2. **Override losing the cascade** (block placed before the `print.css` link) → Task 1 `test_reports_page_declares_landscape_page` asserts `html.index("print.css") < html.index("size: A4 landscape")`
3. **Ticket-detail printout accidentally going landscape** → Task 1 `test_reports_page_declares_landscape_page` asserts the detail HTML has no `size: A4 landscape`; Task 2 `test_print_css_portrait_default_kept` asserts `landscape` never appears in `print.css`
4. **Phone stacked-table rules leaking into print** (thead hidden, rows blown into blocks) → Task 2 `test_phone_table_rules_screen_only` asserts `main.css` contains `@media screen and (max-width: 767.98px)` and no bare `@media (max-width: 767.98px)`
5. **`break-inside: avoid` on the table's card pushing a long table to a single page** → Task 2 `test_print_css_fit_rules` asserts the avoid rule is scoped to `.printable .row` (the summary/breakdown rows), never to the table card
6. **Edit wiping the existing pagination rules** (repeating header, no split rows) → Task 2 `test_print_css_fit_rules` asserts `table-header-group` and `page-break-inside: avoid` survive in `print.css`

---

### Task 1: Landscape `@page` scoped to the reports page

**Files:**
- Modify: `app/templates/base.html` (add empty `page_css` block at end of `<head>`, after the accent `<style>` block)
- Modify: `app/templates/reports/index.html` (fill the block with the landscape `@page` rule)
- Test: `tests/test_reports.py`

**Interfaces:**
- Consumes: Jinja block inheritance (`reports/index.html` extends `base.html`); existing fixtures `client`, `user_factory`, `login`, `ticket_factory`
- Produces: Jinja block `page_css` — empty by default in `base.html`; the reports page renders `<style>` containing `@page { size: A4 landscape; margin: 1.5cm }`. Any future page may fill it the same way; Task 2 does not use it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reports.py` (imports: `Path` from `pathlib` not needed here — only existing imports plus fixtures):

```python
def test_reports_page_declares_landscape_page(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(role="user", username="reports-landscape-req")
    ticket = ticket_factory(requester, subject="LANDSCAPE-TICKET")
    login(client, agent)

    reports_html = client.get("/reports").get_data(as_text=True)

    assert "size: A4 landscape" in reports_html
    # The override must be declared after the print.css link to win the cascade.
    assert reports_html.index("print.css") < reports_html.index("size: A4 landscape")

    login(client, requester)

    detail_html = client.get(f"/tickets/{ticket.id}").get_data(as_text=True)
    assert "size: A4 landscape" not in detail_html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_reports.py::test_reports_page_declares_landscape_page -q`
Expected: FAIL — `AssertionError` on `assert "size: A4 landscape" in reports_html`

- [ ] **Step 3: Implement the `page_css` block**

In `app/templates/base.html`, immediately before `</head>` (after the accent `</style>`), add:

```jinja
    {# Page-level @page overrides (landscape reports). Must stay after the
       print.css <link> above so the later rule wins the cascade. #}
    {% block page_css %}{% endblock %}
```

In `app/templates/reports/index.html`, add the block alongside the existing `title`/`content` blocks (after the `title` block):

```jinja
{% block page_css %}
<style>
  /* Scoped to this document: print.css keeps portrait A4 for the
     ticket-detail printout; this later @page wins the cascade. */
  @page {
    size: A4 landscape;
    margin: 1.5cm;
  }
</style>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_reports.py -q`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: all green

```bash
git add app/templates/base.html app/templates/reports/index.html tests/test_reports.py
git commit -m "feat: landscape A4 @page for the reports print output"
```

---

### Task 2: Compact print fit + screen-scope phone table rules

**Files:**
- Modify: `app/static/css/print.css` (new compact rules inside the existing `@media print` block)
- Modify: `app/static/css/main.css` (line ~350: `@media (max-width: 767.98px)` → `@media screen and (max-width: 767.98px)` on the `.table-stack` block)
- Test: `tests/test_reports.py`

**Interfaces:**
- Consumes: markup fixed by Task 1's page and the existing template — `.printable` wraps summary `.row`s, breakdown `.row`s, then the table `.card` as a direct child; `.fs-2` holds the stat counts
- Produces: no code interfaces — CSS only. Test names: `test_print_css_fit_rules`, `test_print_css_portrait_default_kept`, `test_phone_table_rules_screen_only`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_reports.py` (add `from pathlib import Path` at the top; `_CSS = Path(__file__).resolve().parents[1] / "app" / "static" / "css"` as a module constant):

```python
def test_print_css_fit_rules():
    css = (_CSS / "print.css").read_text(encoding="utf-8")

    # Pagination basics must survive any edit to the fit rules.
    assert "table-header-group" in css
    assert "page-break-inside: avoid" in css
    # Compact landscape table.
    assert "font-size: 9pt" in css
    # Cards avoid breaks, but only the summary/breakdown rows — the ticket
    # table's own card must stay free to paginate across pages.
    assert ".printable .row" in css
    assert ".printable .card {" not in css


def test_print_css_portrait_default_kept():
    css = (_CSS / "print.css").read_text(encoding="utf-8")

    # Landscape lives only in the reports page's page_css block, never here:
    # this file serves the ticket-detail printout too.
    assert "size: A4" in css
    assert "landscape" not in css


def test_phone_table_rules_screen_only():
    css = (_CSS / "main.css").read_text(encoding="utf-8")

    # Print viewports can match a bare max-width query; the stacked-phone
    # table must never trigger when printing.
    assert "@media screen and (max-width: 767.98px)" in css
    assert "@media (max-width: 767.98px)" not in css
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reports.py::test_print_css_fit_rules tests/test_reports.py::test_phone_table_rules_screen_only -q`
Expected: FAIL — `font-size: 9pt` missing from `print.css`; bare `@media (max-width: 767.98px)` still in `main.css` (`test_print_css_portrait_default_kept` passes already — it pins current state)

- [ ] **Step 3: Implement the CSS changes**

In `app/static/css/print.css`, add inside the existing `@media print` block (keeping the current `@page`, body, chrome-hiding, `thead`, and `tr` rules unchanged):

```css
  /* Report rows of cards: keep each row intact across page breaks and drop
     screen shadows. Scoped to .row — the ticket table's card (a direct
     child of .printable, not inside a row) must still paginate. */
  .printable .row {
    break-inside: avoid;
  }

  .printable .row .card {
    box-shadow: none;
  }

  .printable .row .card .card-body {
    padding: 0.35rem 0.5rem;
  }

  .printable .fs-2 {
    font-size: 1.35rem;
  }

  /* Landscape: tighter type so nine table columns fit the page width.
     Cells wrap by default — no nowrap anywhere. */
  .printable .table {
    font-size: 9pt;
  }

  .printable .table td,
  .printable .table th {
    padding: 0.25rem 0.4rem;
  }
```

In `app/static/css/main.css`, change the `.table-stack` block's opening line (the one under the `Phones:` comment) to:

```css
@media screen and (max-width: 767.98px) {
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reports.py -q`
Expected: PASS (all, including Task 1's)

- [ ] **Step 5: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: all green

```bash
git add app/static/css/print.css app/static/css/main.css tests/test_reports.py
git commit -m "fix: compact report print fit and screen-scope phone table rules"
```
