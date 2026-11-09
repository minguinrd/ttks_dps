# Design: Internal Tech-Support Ticketing App (ttks_dps)

Date: 2026-11-09
Status: awaiting human approval

## Intent and why

A small office has no ticket system. Tech support is one person; employees find them directly when issues come up, so nothing is tracked, prioritized, or visible. This app replaces ad-hoc interruptions with a shared queue: employees submit tickets, agents claim and resolve them, and an admin controls who gets accounts. Success = every issue is logged, traceable to an owner, and visible until it is closed.

## Goals (v1)

- Employee self-registration; an admin must approve before the account can log in
- Three roles: `user`, `agent`, `admin`
- Ticket lifecycle: `open → assigned → resolved ⇄ reopen → closed`, with a comment thread
- Ticket fields: sequential display number, subject, description, category, priority, requester, assignee, department, timestamps, resolution note
- Categories (static): Hardware, Software, Network, Access, Other
- Priorities: Low, Normal, High, Urgent
- Internal notes on tickets, visible only to agents/admins
- Admin area: approve pending registrations, manage users (role, department, suspend/reactivate, reset password), manage departments, small dashboard (open counts, by-category/priority breakdown, pending approvals)
- In-app notifications with an unread badge (no email in v1)
- Profile picture upload; users edit their own profile/password
- Runs with Docker + Docker Compose; SQLite in WAL mode on a persistent volume

## Non-goals (v1)

- Google login (planned later; v1 is username + password only)
- Email/SMTP notifications
- File attachments on tickets (avatar upload only)
- SLA timers, auto-close, overdue escalation, reporting beyond the simple dashboard
- Public/anonymous submission, multi-office/multi-tenant, REST API, mobile app
- Realtime push (badge refreshes on navigation in v1)

## Anti-goals

- No over-engineering: no service/repository layering, message queues, Redis, Celery, or API-first design
- No security shortcuts either: CSRF on all forms, hashed passwords, parameterized ORM queries, server-side authorization on every route (never trust the template)

## Constraints

- Given stack: Python + Flask, Jinja2 + Bootstrap 5 + SweetAlert2, SQLite (WAL) + SQLAlchemy, Docker + Docker Compose
- Internal app on an office network, but still standard web hardening
- Account activation is admin-gated; a pending user cannot log in

## Approaches considered (structure)

1. **Single flat Flask module** — fastest to start, becomes unmanageable past ~10 routes, mixes admin and public concerns. Rejected.
2. **App factory + blueprints per domain** (`auth`, `tickets`, `admin`, `main`), Flask-WTF forms, Flask-Login, Flask-Migrate, pytest — **chosen**. Standard Flask practice, isolates the admin area, factory enables clean tests, migrations keep SQLite schema evolvable.
3. **Layered architecture (service/repository, DI)** — ceremony without payoff at this scale. Rejected.

Django and a JS SPA were also viable general-purpose options but are ruled out by the chosen stack (Jinja2 server rendering).

## Decisions (the how)

### Auth and accounts

- Username + password login via Flask-Login sessions; passwords hashed with werkzeug's `generate_password_hash`
- Role checks through decorators (`login_required`, `role_required("agent"|"admin")`) applied per route
- `User.status`: `pending` (registered, awaiting approval) → `active` (admin approved) or `suspended` (admin blocked/rejected; login refused with a distinct message)
- Registration is open; after submitting, the user sees a "waiting for approval" page and cannot log in until active
- User fields: username, password hash, full name, email, department, status, profile picture, role, created/updated timestamps
- Profile picture: jpg/png/webp upload (≈2 MB max), stored on the data volume, served through an authenticated route
- Admin-created accounts start `active` (creating the account *is* the approval) with an admin-set initial password and a must-change-password flag enforced on first login; admin password resets set the same flag. Self-registered users keep their own chosen password.

### Roles and permissions

- **user**: create/view own tickets, post public comments, reopen/close own resolved tickets, edit own profile, change own password, upload avatar
- **agent**: everything above + see the full queue, claim tickets, comment (public + internal notes), resolve/close/reopen any ticket
- **admin**: everything above + approve/reject registrations, create/edit users, change roles, suspend/reactivate, reset passwords, CRUD departments, view all tickets, dashboard
- Visibility rule: regular users see only their own tickets and never see internal comments (enforced server-side, not just hidden in templates)

### Tickets

- Model fields: display ticket number (sequential), subject, description, category (static enum), priority, status, `requester_id`, `assignee_id` (nullable), `department_id` (copied from requester at creation), created/updated/resolved/closed timestamps, resolution note
- Status machine:
  - `open → assigned`: agent self-claims from the queue; admin may assign to any agent
  - `assigned → open`: assignee or admin releases the ticket back to the queue (unclaim)
  - `assigned → assigned`: admin reassigns to a different agent (a system comment records it)
  - `assigned → resolved`: assignee or admin, resolution note required
  - `resolved → assigned`: requester or agent/admin reopens (a system comment records the reopen)
  - `open`/`assigned → closed`: requester, assignee, or admin, no resolution note required
  - `closed → assigned`: admin only; a `closed` ticket is otherwise frozen — no comments, no field edits
- Comments: body, author, `is_internal` flag, timestamp. Posting a comment on a resolved ticket offers a SweetAlert confirm to reopen it alongside the comment (explicit button also present). Closed tickets accept no comments (comment box not rendered; route rejects server-side).
- Field edits (subject, description, category, priority): requester only while status is `open`; agents/admins any time except `closed` (admin reopens first). Edits bump `updated_at`; no thread entry is created.
- Users can comment only on their own tickets; agents/admins on any ticket

### Notifications

- `Notification` rows for: ticket claimed/assigned to you, new public comment on your ticket, status changes on your ticket, new pending registration (admins), reopen events
- Unread badge in the navbar; a notifications page with mark-one/mark-all-read
- v1 refreshes on navigation only (no polling/websockets)

### Admin and dashboard

- Pending-approval queue with Approve (→ active) and Reject (→ suspended)
- Users table with filters (status, department), inline actions: edit profile fields, change role/department, suspend/reactivate, reset password
- Departments: simple CRUD (unique names); a department with users cannot be deleted
- Dashboard: counts (open, assigned, resolved this week, pending users), breakdowns by category and priority, oldest unassigned ticket, and a flag on tickets assigned to suspended/inactive agents (so handover gaps are visible)

### UI pages

- Login, Register, Pending-approval screen
- Navbar per role: links, notification bell with badge, avatar dropdown (profile, logout)
- **My Tickets** (default for `user`): list with status/priority/category badges + New Ticket button
- **Queue** (agents/admin): filters for status, category, priority, department, requester; claim button
- **Ticket detail**: header with number/subject/badges/requester/assignee, contextual action buttons (claim, resolve, reopen, close), thread with visually distinct internal notes, comment box with internal-note toggle for agents/admins, resolution block
- Profile: edit full name/email, change password, upload avatar
- Admin: dashboard, users (pending/all), departments
- SweetAlert2 for destructive confirmations and toasts; server-rendered forms with inline validation errors

### Data and files

- SQLAlchemy models: `User`, `Department`, `Ticket`, `Comment`, `Notification`
- SQLite WAL enabled on every connection (`PRAGMA journal_mode=WAL`)
- Single named Docker volume holds the DB and avatar uploads
- Flask-Migrate (Alembic) from day one; migrations run on container start
- Initial admin: auto-seeded on first startup from env vars (`ADMIN_USERNAME` / `ADMIN_PASSWORD`) when no admin exists

### Config and deployment

- Config via environment: `SECRET_KEY`, data directory path, upload limits
- Production container: gunicorn serving the Flask app factory; Compose maps one port, named volume for `/data`, `restart: unless-stopped`
- Local dev: `flask run` with debug against the same code; no separate dev stack required
- `.env`-driven configuration, `.env.example` committed

### Testing

- pytest against the app factory with a temporary SQLite database
- Must-cover: registration → pending → approval → login flow; role/permission enforcement per route; status transitions incl. invalid ones; internal comments never rendered to regular users; claim/resolve/reopen/close rules
- Verification order before any merge: lint → typecheck (if configured) → tests

## What's left to the builder

Exact route table, form field validation details, template/layout structure, notification event wiring, seed/CLI details, test file layout, and exact commands — all to be derived consistently with the decisions above during planning.
