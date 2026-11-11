# Reports (Print/PDF) + Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add printable/PDF reports (summary + filtered ticket list + single-ticket print) and a backup module (daily snapshot, admin trigger/download, restore CLI).

**Architecture:** Three independent tasks: a `reports` blueprint rendering one print-optimized document behind `@media print` CSS (browser print dialog = PDF, no new dependencies); an `app/backup.py` module using SQLite `VACUUM INTO` with a scheduler thread and an admin page; a `restore-backup` CLI command with integrity checking and a safety copy. Tasks 2 and 3 share `app/backup.py` helpers only through documented names.

**Tech Stack:** Existing stack — Flask, Jinja2 + Bootstrap 5, SQLAlchemy/SQLite (WAL), Flask-WTF, pytest + ruff. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-11-11-reports-backup-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Reports: `role_required("agent", "admin")` on `/reports`; 403 for `user`, anonymous redirected to login. Single-ticket Print button follows existing ticket visibility (requester may print own ticket)
- Print output: navbar/buttons/chrome hidden (`no-print` class), A4 page size with margins, table headers repeat across pages, ticket/row elements never split across pages
- **No new dependencies** — print/PDF is the browser print dialog (`window.print()`); server-side or JS PDF libraries are explicitly rejected by the spec
- Backups: SQLite `VACUUM INTO` (consistent under WAL, no interruption); files at `DATA_DIR/backups/ttks_dps-YYYYMMDD-HHMMSS.db` (UTC timestamp); env `BACKUP_HOUR` default `03:00`, `BACKUP_KEEP` default `7`
- Backup routes and download: `role_required("admin")`, state-changing routes POST+CSRF; download path must be validated against traversal (reject any name not matching the backup filename pattern inside `BACKUP_DIR`)
- Restore CLI: refuse files failing `PRAGMA integrity_check`, refuse the live DB path itself, always create a safety copy `pre-restore-<UTCtimestamp>.db` before replacing, delete stale `<db>-wal`/`<db>-shm` sidecars after replacing
- Scheduler thread must never start when `app.testing` is true
- Every task ends green: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` (if format check fails, run `.venv/bin/ruff format .` then re-check)
- Python 3.15 locally / 3.12 in the image; no network I/O in tests

## Review Focus

1. **Path traversal via backup download name** → Task 2 `test_download_path_traversal_rejected` (name like `../ttks_dps.db` → 404, nothing served)
2. **Restore on a corrupt file destroying the live DB** → Task 3 `test_restore_rejects_corrupt_file` (garbage input → non-zero exit, live DB byte-identical)
3. **Stale WAL sidecars corrupting a restored DB** → Task 3 `test_restore_cleans_wal_sidecars` (pre-planted `-wal`/`-shm` gone after restore)
4. **`date_to` boundary excluding tickets created on the chosen end date** → Task 1 `test_reports_date_filter_scopes_summary` (a ticket created on `date_to` at 23:59 IS included)
5. **Scheduler thread leaking into tests** → Task 2 `test_scheduler_not_started_in_testing` (TESTING app never calls `start_scheduler`; non-testing app does)

---

### Task 1: Reports page + print styles

**Files:**
- Create: `app/reports/__init__.py`, `app/reports/routes.py`, `app/reports/forms.py`, `app/templates/reports/index.html`, `app/static/css/print.css`, `tests/test_reports.py`
- Modify: `app/__init__.py` (register blueprint), `app/templates/base.html` (Reports nav link for agent/admin; `<link>` for `print.css` with `media="print"`), `app/templates/tickets/detail.html` (Print button)

**Interfaces:**
- Consumes: `role_required` (`app/permissions.py`), `Ticket`/`Department` models, enums `TicketStatus`/`Category`/`Priority`, conftest fixtures (`app`, `client`, `user_factory`, `login`, `db_schema`, `ticket_factory`), base layout + `data-confirm` JS already in `base.html`
- Produces:
  - Blueprint `reports` registered in `create_app`; route `reports.index` `GET /reports` accepting optional query params `date_from`, `date_to` (`YYYY-MM-DD`), `status`, `category`, `priority`, `department_id`, `requester_id`
  - `ReportForm` (FlaskForm): `date_from`/`date_to` as `wtforms.DateField` (optional), the five queue-style `SelectField`s (optional, empty = no filter) with choices built the same way the queue form builds them
  - Filter semantics: successive narrowing on `Ticket` query; `date_from` → `created_at >= 00:00:00` of that date; `date_to` → `created_at < (date_to + 1 day)` (end date inclusive); newest first
  - Summary dict computed from the SAME filtered queryset: `total`, counts per status (`open`, `assigned`, `resolved`, `closed`), `by_category`, `by_priority`, `oldest_unassigned` (min `created_at` among filtered where status `open` and no assignee, else `None`)
  - Template structure: `reports/index.html` extends `base`; filter form and buttons carry class `no-print`; report content (summary cards + ticket table) inside `<div class="printable">`; a button `<button class="btn btn-secondary no-print" onclick="window.print()">Print / Save as PDF</button>`
  - `print.css`: only `@media print` rules — hide `.navbar`, `.no-print`, flash messages; `@page { size: A4; margin: 1.5cm }`; `thead { display: table-header-group }`; `tr { page-break-inside: avoid }`; base font ~10pt
  - `detail.html`: same Print button (visible to whoever can view the ticket)
  - `base.html`: `<link rel="stylesheet" href="{{ url_for('static', filename='css/print.css') }}" media="print">` in `<head>`; nav item `Reports` shown for `current_user.role in ("agent", "admin")` linking `/reports`

- [ ] **Step 1: Write the failing tests**

`tests/test_reports.py`:
- `test_reports_requires_agent` — `user_factory(role="user")` + `login` → `GET /reports` → 403; anonymous → redirect to login
- `test_reports_renders_summary_and_list` — seeded tickets (different statuses/categories) → 200; response contains the ticket subjects and the summary counts
- `test_reports_date_filter_scopes_summary` — three tickets: one created 3 days ago, one created today at 23:59 (set `created_at` explicitly), one created 10 days ago; `?date_from=<today-1>&date_to=<today>` → only today's ticket in table; summary `total == 1`
- `test_reports_status_filter` — `?status=open` returns only open tickets in the table
- `test_print_button_present` — `GET /reports` contains `window.print()`; `GET /tickets/<id>` (requester) also contains it
- `test_print_css_linked` — `GET /` (any logged-in page) contains `print.css`

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reports.py -q`
Expected: FAIL (route missing → 404)

- [ ] **Step 3: Implement blueprint, form, template, print CSS, nav**

Per the Produces block; register the blueprint in `create_app` alongside the existing ones; build `SelectField` choices with the same query style the queue route uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reports.py -q`
Expected: PASS (all 6)

- [ ] **Step 5: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Then: `git add -A && git commit -m "feat: printable reports with date and queue filters"`

---

### Task 2: Backup core + scheduler + admin page

**Files:**
- Create: `app/backup.py`, `app/templates/admin/backup.html`, `tests/test_backup.py`
- Modify: `app/config.py` (three keys), `app/__init__.py` (start scheduler when not testing), `app/admin/routes.py` (three routes), `app/templates/base.html` or admin nav (Backup link for admin)

**Interfaces:**
- Consumes: `create_app`, `Config` env-reading pattern, `role_required("admin")`, admin flash+redirect conventions, conftest fixtures
- Produces:
  - Config: `BACKUP_HOUR` (`os.environ.get("BACKUP_HOUR", "03:00")`), `BACKUP_KEEP` (`int(os.environ.get("BACKUP_KEEP", "7"))`), `BACKUP_DIR` (`os.path.join(DATA_DIR, "backups")`)
  - `app/backup.py`:
    - `db_path_from_uri(uri: str) -> Path` — strips `sqlite:///` (same rule as `tests/test_migrations.py::_db_path`)
    - `create_backup() -> Path` — connects to the live DB with `sqlite3`, executes `VACUUM INTO ?` with target `BACKUP_DIR / f"ttks_dps-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"` (create dir first), returns the path
    - `prune_backups(keep: int) -> int` — deletes oldest files matching the `ttks_dps-*.db` pattern beyond `keep` (timestamp names sort lexicographically), returns count deleted
    - `run_backup_cycle() -> Path` — `create_backup()` then `prune_backups(app.config["BACKUP_KEEP"])`; the shared entry point for scheduler and admin button
    - `start_scheduler(app: Flask) -> None` — daemon thread: loop sleeping until next `BACKUP_HOUR` (parse `HH:MM`; recompute after each run), then `with app.app_context(): run_backup_cycle()`; swallow+log per-cycle errors so the thread survives
  - `create_app` calls `start_scheduler(app)` ONLY when `not app.testing`
  - Admin routes (all `role_required("admin")`): `admin.backup_page` `GET /admin/backup` (list files: name, size bytes, mtime; "Back up now" form); `admin.backup_create` `POST /admin/backup/create` (runs `run_backup_cycle()`, flash, redirect); `admin.backup_download` `GET /admin/backup/<name>/download` — validate `name` with `re.fullmatch(r"ttks_dps-\d{8}-\d{6}\.db", name)` and ` (BACKUP_DIR / name).resolve().parent == BACKUP_DIR.resolve()` else 404; `send_file(..., as_attachment=True)`
  - Template `admin/backup.html` extends `base`; download links carry `no-print`

- [ ] **Step 1: Write the failing tests**

`tests/test_backup.py`:
- `test_create_backup_produces_valid_sqlite` — call `create_backup()` with `BACKUP_DIR` pointed at `tmp_path` (via app config) → file exists, `PRAGMA integrity_check` == `ok`, `users` table present
- `test_prune_keeps_newest_n` — plant 9 dummy `ttks_dps-YYYYMMDD-HHMMSS.db` files with increasing timestamps plus 1 non-matching file; `prune_backups(7)` → 2 matching deleted, non-matching untouched
- `test_backup_now_creates_file` — admin `POST /admin/backup/create` → 302, new file in `BACKUP_DIR`
- `test_backup_requires_admin` — `user_factory(role="agent")` + `login`: `GET /admin/backup` → 403 and `POST /admin/backup/create` → 403; same for `role="user"`
- `test_download_returns_file` — admin `GET /admin/backup/<created name>/download` → 200, `Content-Disposition` contains `attachment`
- `test_download_path_traversal_rejected` — `GET /admin/backup/..%2Fttks_dps.db/download` (and plain `../` variant) → 404
- `test_scheduler_not_started_in_testing` — monkeypatch `app.backup.start_scheduler`; `create_app({"TESTING": True, ...})` → not called; `create_app({..."TESTING": False...})` → called once with the app (ensure monkeypatched so no real thread starts)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_backup.py -q`
Expected: FAIL (module/routes missing)

- [ ] **Step 3: Implement config keys, `app/backup.py`, scheduler hook, admin routes, template**

Per the Produces block. In `create_app`, guard the scheduler with `if not app.testing:` after blueprint registration.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_backup.py -q`
Expected: PASS (all 7)

- [ ] **Step 5: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Then: `git add -A && git commit -m "feat: daily sqlite backups with admin trigger and download"`

---

### Task 3: Restore CLI + docs

**Files:**
- Modify: `app/cli.py` (new command beside `seed-admin`), `README.md` (Backups runbook), `AGENTS.md` (env vars + commands), `.env.example`, `docker-compose.yml` (BACKUP_HOUR/BACKUP_KEEP passthrough with defaults)
- Create: `tests/test_restore.py`

**Interfaces:**
- Consumes: `app/backup.py::db_path_from_uri`, `Config.DATA_DIR`/`BACKUP_DIR`, `app.cli` registration pattern in `create_app`, conftest fixtures
- Produces: command `flask restore-backup <path>`:
  - missing arg or nonexistent file → print error, exit code 1, no changes
  - `PRAGMA integrity_check` on `<path>` != `ok` → print error, exit 1, live DB untouched
  - `<path>` resolving to the live DB path → refuse, exit 1
  - otherwise: copy live DB (if it exists) to `DATA_DIR/pre-restore-<UTCtimestamp>.db`, then `shutil.copy2(<path>, live_db)`, then unlink stale `live_db-wal` and `live_db-shm` if present; print success + `Restart the service to apply the restored database.`; exit 0

- [ ] **Step 1: Write the failing tests**

`tests/test_restore.py` (fresh temp app like `tests/test_migrations.py`, CliRunner):
- `test_restore_rejects_corrupt_file` — write a file of random bytes; snapshot live DB bytes; invoke `restore-backup <garbage>` → exit code != 0; live DB bytes unchanged
- `test_restore_replaces_database` — fresh DB, insert a user via raw SQL; copy the DB to `backup.db`; insert a second user into the live DB; invoke `restore-backup backup.db` → exit 0; live DB has exactly the first user again
- `test_restore_takes_safety_copy` — after the previous flow: a `pre-restore-*.db` exists in `DATA_DIR` whose user set matches the pre-restore state
- `test_restore_cleans_wal_sidecars` — plant `live.db-wal` and `live.db-shm` files before invoking → both gone after exit 0
- `test_restore_missing_file_fails` — invoke with a nonexistent path → exit 1

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_restore.py -q`
Expected: FAIL (no such command)

- [ ] **Step 3: Implement the CLI command**

In `app/cli.py` beside `seed-admin`: `@click.command("restore-backup")` + `@click.argument("path", type=click.Path(exists=False))`, `@with_appcontext`; resolve live DB via `db_path_from_uri(current_app.config["SQLALCHEMY_DATABASE_URI"])`; follow the Produces contract exactly (integrity check first, safety copy second, sidecar cleanup last).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_restore.py -q`
Expected: PASS (all 5)

- [ ] **Step 5: Docs + config passthrough**

- `README.md` — new **Backups** section: daily automatic snapshot (when the app runs), `BACKUP_HOUR`/`BACKUP_KEEP`, admin page path, download for off-machine copies (with the explicit note that same-volume backups are not off-box protection), and the restore runbook: `docker compose stop web` → `docker compose run --rm --entrypoint flask web restore-backup /data/backups/<file>` → `docker compose start web`
- `AGENTS.md` — add `BACKUP_HOUR`/`BACKUP_KEEP` to the env-var gotcha and `flask restore-backup <path>` to commands
- `.env.example` + `docker-compose.yml` — the two backup vars with defaults `03:00` / `7`

- [ ] **Step 6: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Then: `git add -A && git commit -m "feat: restore-backup cli with integrity check and backup docs"`

---

## Post-conditions

- Any agent/admin page prints cleanly to A4/PDF via the browser dialog; no PDF dependencies added
- With the stack running, a backup appears in `DATA_DIR/backups/` daily at `BACKUP_HOUR` and after the admin button; 7 newest kept by default
- `flask restore-backup` swaps databases safely (integrity check + safety copy + WAL cleanup) and the README documents the full runbook
