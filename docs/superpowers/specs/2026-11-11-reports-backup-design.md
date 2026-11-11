# Design: Reports (Print/PDF) + Backup Module (ttks_dps)

Date: 2026-11-11
Status: approved in conversation (short design; no builder check)
Size: small-to-medium change — two independent features in one plan

## Intent and why

Staff need paper/PDF artifacts of ticket data (reviews, filing, handovers) and the
single-SQLite office needs a safety net against disk/container loss. Today there
is no print styling, no PDF code, and no backup anywhere in the app.

## Goals

- **A. Summary report:** dashboard-style numbers (counts, breakdowns by
  category/priority, oldest unassigned) on one printable page, scoped to filters
- **B. Ticket list report:** the filtered ticket set as a printable table with a
  date range (created from/to) plus status/category/priority/department/requester
- **C. Single ticket print:** the existing detail page (header, thread,
  resolution) formatted for paper
- Both print and "export to PDF" via the browser's print dialog (*Save as PDF*)
- **Backup:** automatic daily snapshot at 03:00 (env-configurable), keep last 7,
  stored in `DATA_DIR/backups/`; admin UI to trigger a backup now, list
  backups, and download one; `flask restore-backup <file>` CLI for restores

## Non-goals

- No server-side PDF libraries, no JS-to-PDF libraries, no email delivery
- No CSV/Excel export, no off-site replication (README documents that
  same-volume backups are not off-box protection)
- No restore-from-UI (CLI only, deliberately)

## Constraints

- Reports page is `role_required("agent", "admin")`; the single-ticket print
  button follows existing ticket visibility (a requester may print their own)
- Print output must hide chrome (navbar, buttons), use A4-friendly margins,
  repeat table headers, and avoid splitting ticket rows across pages
- Backups use SQLite online backup semantics (`VACUUM INTO`) — consistent under
  WAL, no service interruption
- Restore refuses to run on a file failing `PRAGMA integrity_check` and always
  takes a safety copy of the current DB before swapping
- Existing pinned strings, role gates, POST+CSRF conventions unchanged

## Approaches considered

1. **Browser print + `@media print` stylesheet** — chosen: one mechanism
   serves print and PDF; zero dependencies; tables render faithfully.
2. **WeasyPrint server-side HTML→PDF** — rejected: adds system packages
   (pango/cairo) to the image for output the browser already produces.
3. **jsPDF/html2canvas client-side** — rejected: poor table fidelity, heavier
   front-end for no benefit.

For backup: an **in-app scheduler thread** was chosen over a container cron
sidecar (no new system dependency, always running with the app) and over
start-only backups (would miss multi-day uptime).

## Decisions (the how)

- **Reports route:** `GET /reports` (form with filters + Generate → summary
  block + ticket table in one printable document); print button triggers
  `window.print()`; new `app/static/css/print.css` with `@media print` rules
- **Ticket detail:** Print button (existing visibility rules), same stylesheet
- Filter params reuse the queue's names (`status`, `category`, `priority`,
  `department_id`, `requester_id`) plus `date_from`/`date_to` on `created_at`
- **Backup storage:** `DATA_DIR/backups/ttks_dps-YYYYMMDD-HHMMSS.db`; env
  `BACKUP_HOUR` (default `03:00`), `BACKUP_KEEP` (default `7`)
- **Scheduler:** daemon thread started from `create_app` when not `TESTING`,
  calling the same `create_backup()` function the admin button uses
- **Admin UI:** new Backup section (admin dashboard or nav): "Back up now"
  (POST), list with name/size/created, download via `send_file` as attachment
- **CLI:** `flask restore-backup <path>` — integrity check → safety copy
  `pre-restore-<timestamp>.db` → replace live DB → print "restart the service"
- Docs: README (backup/restore runbook + off-box note), AGENTS.md (env vars,
  new commands)
- Tests: report permissions, filter scoping, print-button presence, print CSS
  hook; backup creation + retention + download authz + admin-only gates;
  restore CLI refuses corrupt input and succeeds on valid input; scheduler
  function tested by direct invocation (never via thread in tests)

## What's left to the builder

Exact template markup, filter form fields, notification-free integration with
existing pages, backup listing layout, CLI message wording — all consistent
with the decisions above.
