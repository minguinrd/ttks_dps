# Ticket Webapp (ttks_dps) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved internal tech-support ticketing webapp (registration + admin approval, 3 roles, ticket lifecycle, in-app notifications, admin area) per the spec.

**Architecture:** Flask app-factory with four blueprints (`auth`, `main`, `tickets`, `admin`); server-rendered Jinja2 + Bootstrap 5; SQLAlchemy models own the ticket status machine and raise `InvalidTransition`; role checks via a `role_required` decorator; Flask-Login sessions; Flask-Migrate migrations run at container start.

**Tech Stack:** Python 3 (venv at `.venv/`), Flask 3, Flask-SQLAlchemy 3, Flask-Login, Flask-WTF, Flask-Migrate, SQLite (WAL), Jinja2 + Bootstrap 5 + SweetAlert2 (CDN), pytest + ruff, Docker + Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-09-ticket-webapp-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Roles exactly `user`, `agent`, `admin` (`Role` StrEnum in `app/models/user.py`, column stores `.value`)
- User status exactly `pending` | `active` | `suspended`; only `active` may establish a login session
- Ticket status exactly `open` | `assigned` | `resolved` | `closed`
- Categories (static): `hardware`, `software`, `network`, `access`, `other`
- Priorities: `low`, `normal`, `high`, `urgent`
- Internal comments (`is_internal=True`) must never be rendered to or settable by role `user` — enforced server-side
- All state-changing routes: POST only, CSRF protected (Flask-WTF); failures of role checks → HTTP 403; access to another user's ticket as `user` → HTTP 404 (do not leak existence)
- SQLite: `PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys=ON` on every new DBAPI connection
- No email, no ticket attachments, no realtime: in-app notifications only (badge refreshes on navigation)
- Pinned login refusal strings: pending → `Your account is awaiting admin approval.`; suspended → `This account has been suspended. Contact the administrator.`; bad credentials → `Invalid username or password.`; forced change → `You must change your password before continuing.`
- Avatar uploads: jpg/png/webp only, max 2 MB, stored under `AVATAR_DIR`, served via authenticated route
- Bootstrap 5 + SweetAlert2 from CDN in `base.html` (vendoring is a later concern)
- Every task ends green: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` (if the format check fails, run `.venv/bin/ruff format .` then re-check)
- Python here is 3.15: if a dependency floor below fails to install, bump to a version that installs and keep the working pin
- **Plan addition (flagged to human):** the spec's status machine listed `closed` only from `open`/`assigned`; this plan also allows `resolved → closed` (requester/assignee/admin) because confirm-and-close from resolved is the normal path

## Review Focus

1. **Internal comments leaking to regular users** (template or forged POST) → Task 5: `test_internal_comment_hidden_from_requester`, `test_user_cannot_forge_internal_flag`
2. **Role escalation** (user on queue, agent on admin) → Task 3 `test_role_required_forbids_other_roles`, Task 7 `test_queue_requires_agent_role`, Task 9 `test_agent_forbidden_from_admin`
3. **Invalid ticket transitions mutating state** → Task 6: invalid-transition tests assert status/assignee unchanged
4. **Pending/suspended login bypass and forced-password-change gate** → Task 3: `test_pending_user_cannot_login`, `test_suspended_login_refused`; Task 4: `test_forced_password_change_gate`
5. **Avatar upload abuse** (oversize, wrong type, path tricks) → Task 4: `test_avatar_wrong_type_rejected`, `test_avatar_oversize_rejected`

---

### Task 1: Scaffold + app factory

**Files:**
- Create: `.gitignore`, `.env.example`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `wsgi.py`, `app/__init__.py`, `app/config.py`, `app/extensions.py`, `tests/conftest.py`, `tests/test_scaffold.py`
- Modify: none (repo has no git yet — `git init` here)

**Interfaces:**
- Consumes: nothing
- Produces: `create_app(config: dict | None = None) -> Flask` in `app/__init__.py`; extensions `db, migrate, csrf, login_manager` in `app/extensions.py`; `Config`/`TestConfig` classes in `app/config.py`; conftest fixtures `app`, `client` (all later tasks use them)

- [ ] **Step 1: Initialize repo and write config files**

`git init`. `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `data/`, `.pytest_cache/`, `.ruff_cache/`. `requirements.txt` floors: `Flask>=3.1`, `Flask-SQLAlchemy>=3.2`, `Flask-Login>=0.6.3`, `Flask-WTF>=1.2`, `Flask-Migrate>=4.0`, `WTForms>=3.2`, `email-validator>=2.2`, `gunicorn>=23.0`. `requirements-dev.txt`: `-r requirements.txt`, `pytest>=8.3`, `ruff>=0.9`. `pyproject.toml`: ruff `target-version = "py311"`, line-length 100, lint select `["E", "F", "I"]`; pytest `testpaths = ["tests"]`. `.env.example`: `FLASK_APP=wsgi:app`, `SECRET_KEY=change-me`, `DATA_DIR=./data`, `ADMIN_USERNAME=admin`, `ADMIN_PASSWORD=change-me`.

- [ ] **Step 2: Create venv and install**

Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
Expected: installs cleanly (bump floors if Python 3.15 blocks a package; keep the working pin)

- [ ] **Step 3: Write the failing tests**

`tests/test_scaffold.py`:

```python
def test_create_app_boots_with_test_config(app):
    assert app.config["TESTING"] is True
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")

def test_sqlite_wal_enabled_on_connect(app):
    from sqlalchemy import text
    with app.app_context():
        mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"
```

`tests/conftest.py`: `app` fixture = `create_app({"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db", "WTF_CSRF_ENABLED": False, "AVATAR_DIR": str(tmp_path / "avatars")})` (create the avatars dir); `client` fixture = `app.test_client()`.

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest -q`
Expected: FAIL — `ModuleNotFoundError: app` / import error

- [ ] **Step 5: Implement factory, config, extensions**

`app/extensions.py`: `db = SQLAlchemy()`, `migrate = Migrate()`, `csrf = CSRFProtect()`, `login_manager = LoginManager()`; plus a module-level `@event.listens_for(Engine, "connect")` handler that, when the DBAPI connection is `sqlite3.Connection`, executes `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` (register once at import). `app/config.py`: `Config` reads env (`SECRET_KEY` required in production use, `DATA_DIR` default `./data`, DB URI `sqlite:///<DATA_DIR>/ttks_dps.db`, `MAX_CONTENT_LENGTH = 2 * 1024 * 1024`, `AVATAR_DIR = <DATA_DIR>/avatars`, `WTF_CSRF_ENABLED = True`); `TestConfig(Config)` overrides for tests. `app/__init__.py`: `create_app(config=None)` builds the app, merges overrides, ensures `DATA_DIR`/`AVATAR_DIR` exist, inits `db`, `migrate`, `csrf`, `login_manager`, sets `login_manager.login_view = "auth.login"`, returns app. `wsgi.py`: `app = create_app()`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Then: `git add -A && git commit -m "chore: scaffold flask app factory with sqlite wal"`

---

### Task 2: Models + initial migration

**Files:**
- Create: `app/models/__init__.py`, `app/models/user.py`, `app/models/ticket.py`, `app/models/notification.py`, `migrations/` (generated), `tests/test_models.py`
- Modify: `app/__init__.py` (register models + migrate; no route changes)

**Interfaces:**
- Consumes: `db` from Task 1
- Produces (every later task depends on these exact names):
  - `Role` (`user|agent|admin`), `TicketStatus` (`open|assigned|resolved|closed`), `Category`, `Priority` — `enum.StrEnum` in `app/models/user.py` (Role) / `app/models/ticket.py` (rest)
  - `Department(id, name unique)`
  - `User(id, username unique, password_hash, full_name, email, department_id, status default "pending", role default "user", must_change_password default False, avatar_path, created_at, updated_at)` with `set_password(pw: str) -> None`, `check_password(pw: str) -> bool`, and `is_active` property returning `self.status == "active"` (overrides `UserMixin`)
  - `Ticket(id` = display number, `subject, description, category, priority, status default "open", requester_id, assignee_id nullable, department_id nullable, resolution_note, created_at, updated_at, resolved_at, closed_at)` with relationships `requester, assignee, department, comments` (ordered by `created_at`) and method `add_system_comment(actor: User, text: str) -> Comment`
  - `Comment(id, ticket_id, author_id, body, is_internal default False, created_at)`
  - `Notification(id, user_id, ticket_id nullable, message, url, is_read default False, created_at)`
  - Exception `InvalidTransition(Exception)` in `app/models/ticket.py` (Task 6 raises it)

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`: `test_user_password_roundtrip` (set/check, wrong password False); `test_user_is_active_property` (active True, pending/suspended False); `test_username_unique`; `test_department_name_unique`; `test_ticket_defaults` (status `open`, `id` assigned); `test_comment_and_notification_roundtrip` with cascades (create ticket + comment + notification, requery, assert present).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_models.py -q`
Expected: FAIL — imports missing

- [ ] **Step 3: Implement the five models + enums + `InvalidTransition`**

Per the Produces block; `werkzeug.security.generate_password_hash/check_password_hash` for passwords; UTC `datetime.utcnow`-style `default=lambda: datetime.now(timezone.utc)` on all timestamps; `__tablename__` = `users`, `departments`, `tickets`, `comments`, `notifications`.

- [ ] **Step 4: Generate the migration**

Run: `.venv/bin/flask --app wsgi db init` then `.venv/bin/flask --app wsgi db migrate -m "initial schema"`
Expected: `migrations/versions/*.py` created covering all five tables; review it, then `.venv/bin/flask --app wsgi db upgrade` succeeds (creates `data/ttks_dps.db`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Then: `git add -A && git commit -m "feat: domain models and initial migration"`

---

### Task 3: Auth blueprint (register, pending, login, roles, forced password change) + `base.html`

**Files:**
- Create: `app/permissions.py`, `app/auth/__init__.py`, `app/auth/routes.py`, `app/auth/forms.py`, `app/templates/base.html`, `app/static/js/app.js`, `app/templates/auth/login.html`, `app/templates/auth/register.html`, `app/templates/auth/pending.html`, `tests/test_auth.py`
- Modify: `app/__init__.py` (register `auth` blueprint)

**Interfaces:**
- Consumes: `User`, `Role`, `login_manager` from Tasks 1–2
- Produces:
  - `role_required(*roles: str)` decorator in `app/permissions.py` — wraps a view, `abort(403)` unless `current_user.role in roles`
  - Routes: `auth.login` `GET/POST /auth/login`, `auth.register` `GET/POST /auth/register`, `auth.logout` `POST /auth/logout`, `auth.pending` `GET /auth/pending`
  - Blueprint `main` created here (`app/main/__init__.py` + `app/main/routes.py`) containing only `main.index` `GET /` — redirects `user` → hardcoded path `/tickets/mine`, `agent`/`admin` → `/tickets/queue` (hardcoded strings, not `url_for`, because the tickets blueprints don't exist yet; Task 4 extends this blueprint, Task 5/7 keep the paths)
  - conftest additions: `user_factory(role="user", status="active", password="pass12345", **overrides) -> User` (commits) and `login(client, user, password="pass12345") -> None` (POSTs `/auth/login`)
  - `base.html`: Bootstrap 5.3 + SweetAlert2 CDN, navbar with per-role links (My Tickets / Queue / Admin), avatar dropdown (Profile, Logout), `{% block content %}`; `app.js`: forms with `data-confirm="msg"` trigger `Swal.fire` confirm before submit

- [ ] **Step 1: Write the failing tests**

`tests/test_auth.py`:
- `test_register_creates_pending_user` — POST valid register form → user row exists, `status == "pending"`, response redirects to `auth.pending`
- `test_pending_user_cannot_login` — pending login refused, session has no user_id, HTML contains `Your account is awaiting admin approval.`
- `test_suspended_login_refused` — contains `This account has been suspended. Contact the administrator.`
- `test_active_user_login_and_logout` — login redirects to `/`, session has user_id; POST `/auth/logout` clears it
- `test_wrong_password_rejected` — contains `Invalid username or password.`
- `test_duplicate_username_rejected` — second register with same username re-renders form with error, no new row
- `test_role_required_forbids_other_roles` — register a dummy view decorated `role_required("admin")` on the test app; client logged in as `user` → 403
- `test_root_redirects_by_role` — assert `Location` header only: `user` → `/tickets/mine`, `agent` → `/tickets/queue` (targets don't exist yet; do not follow the redirect)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth.py -q`
Expected: FAIL — blueprint/routes missing

- [ ] **Step 3: Implement permissions, auth blueprint, base template, guard**

Register form fields: username, password, confirm, full name, email, optional department `SelectField` (choices from `Department`, validators allow empty — departments may not exist yet). On register: create `User(status="pending", role="user")`, redirect `auth.pending`. Login: look up by username; `check_password` fails → pinned bad-credentials flash; `status == "pending"` → pinned pending flash (no session); `status == "suspended"` → pinned suspended flash; `active` → `login_user`. `login_manager.user_loader` loads by id; `unauthorized` redirects to `auth.login`. Create the `main` blueprint with only `main.index` per the Produces block (hardcoded redirect paths).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth.py -q`
Expected: PASS

- [ ] **Step 5: Run full suite + lint, commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` → all green
Then: `git add -A && git commit -m "feat: auth with registration approval, roles, forced password change"`

---

### Task 4: Profile, password change, avatar upload

**Files:**
- Create: `app/main/forms.py`, `app/templates/main/profile.html`, `app/templates/main/profile_password.html`, `tests/test_profile.py`
- Modify: `app/main/routes.py` (blueprint already registered in Task 3; add the routes below)

**Interfaces:**
- Consumes: `user_factory`, `login`, `role_required` from Task 3; `AVATAR_DIR`, `MAX_CONTENT_LENGTH` from Task 1
- Produces routes: `main.profile` `GET/POST /profile` (full name, email), `main.profile_password` `GET/POST /profile/password` (current, new, confirm; clears `must_change_password` on success), `main.avatar_upload` `POST /profile/avatar` (file field `avatar`), `main.serve_avatar` `GET /avatars/<int:user_id>` (`login_required`, 404 if no file)
- Produces guard: `@app.before_request` in the factory allowing only endpoints `{"static", "auth.logout", "main.profile_password"}` for users with `must_change_password` (all other endpoints redirect to `main.profile_password` with the pinned flash `You must change your password before continuing.`)

- [ ] **Step 1: Write the failing tests**

`tests/test_profile.py`: `test_update_profile_fields`; `test_forced_password_change_gate` (user with `must_change_password=True` GET `/` → 302 to `/profile/password` with the pinned flash; `POST /auth/logout` not blocked); `test_change_password_requires_current` (wrong current → error, hash unchanged); `test_change_password_success_and_clears_flag` (sets `must_change_password` False); `test_avatar_upload_valid` (`.png` file saved under `AVATAR_DIR`, `avatar_path` set, `GET /avatars/<id>` → 200 `image/png`); `test_avatar_wrong_type_rejected` (`.txt` named `.png`? use `content_type="text/plain"` and `.txt` name → form error, `AVATAR_DIR` empty); `test_avatar_oversize_rejected` (3 MB payload → form error, no file written); `test_avatar_requires_login` (anonymous GET `/avatars/<id>` → 302 to login)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: FAIL

- [ ] **Step 3: Implement main blueprint routes/forms**

Avatar: validate extension in `{png, jpg, jpeg, webp}` + `mimetype.startswith("image/")` + size ≤ 2 MB in the form; save as `AVATAR_DIR / f"{uuid4().hex}.{ext}"`; delete the previous file if replacing. Password form requires current password even when forced. `must_change_password` cleared only by `main.profile_password` success (avatar/profile updates don't clear it).

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: profile editing, password change, avatar upload"`

---

### Task 5: Tickets core (create, my list, detail, comments, edits)

**Files:**
- Create: `app/tickets/__init__.py`, `app/tickets/routes.py`, `app/tickets/forms.py`, `app/templates/tickets/mine.html`, `app/templates/tickets/detail.html`, `app/templates/tickets/form.html`, `app/templates/macros/badges.html`, `tests/test_tickets_core.py`
- Modify: `app/main/routes.py` (`/` redirect already points here), conftest (`ticket_factory`)

**Interfaces:**
- Consumes: models (Task 2), `role_required`, `login` fixtures (Task 3)
- Produces routes: `tickets.mine` `GET /tickets/mine` (tickets where requester or assignee is me), `tickets.new` `GET/POST /tickets/new`, `tickets.detail` `GET /tickets/<int:ticket_id>` (404 for `user` unless participant; agents/admin any), `tickets.comment` `POST /tickets/<int:ticket_id>/comments`, `tickets.edit` `POST /tickets/<int:ticket_id>/edit`
  - Forms: `TicketForm(subject, description, category SelectField, priority SelectField)`, `CommentForm(body TextArea, is_internal BooleanField)`, `TicketEditForm` = `TicketForm`
  - conftest: `ticket_factory(requester, **overrides) -> Ticket` (commits; defaults subject/description/category/priority/status open)
  - Edit rule (spec): requester may edit only while `status == "open"`; agents/admin any status except `closed`; others → 403; closed edit → 403

- [ ] **Step 1: Write the failing tests**

`tests/test_tickets_core.py`:
- `test_create_ticket_sets_fields_and_status` — status `open`, `requester` = me, `department_id` copied from requester
- `test_mine_list_shows_only_participants` — my requested + assigned-to-me tickets present; unrelated user's absent
- `test_detail_hidden_from_unrelated_user_404`
- `test_agent_sees_any_ticket` — agent GET other's ticket → 200
- `test_post_comment` — comment row created with author, `is_internal` False
- `test_internal_comment_hidden_from_requester` — agent posts internal note; requester GET detail → body string absent from HTML; agent GET → present
- `test_user_cannot_forge_internal_flag` — `user` POSTs `is_internal=y` → stored `False`
- `test_agent_internal_note_visible_to_agent`
- `test_cannot_comment_on_closed` — POST comment to a `closed` ticket → 403, no row created
- `test_requester_edits_while_open` — subject/category/priority updated, `updated_at` bumped
- `test_requester_cannot_edit_assigned` — 403, values unchanged
- `test_agent_edits_resolved_ticket` — agent changes category on `resolved` ticket → ok
- `test_cannot_edit_closed` — 403 for requester and agent on `closed` ticket

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tickets_core.py -q`
Expected: FAIL

- [ ] **Step 3: Implement tickets blueprint + templates**

Create: copy `department_id` from requester; redirect to detail. Detail template: header (number `#<id>`, subject, status/category/priority badges via `macros/badges.html`, requester, assignee), action-button block (placeholder `{% block actions %}` filled by Task 6), thread rendering public comments + internal ones styled distinctly (only if `current_user.role != "user"`), comment form (internal checkbox rendered only for agent/admin; server forces `is_internal=False` for `user`), edit form shown per edit rule. Comment posting on `closed` → 403 (frozen per spec).

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: ticket creation, detail thread, internal notes, field edits"`

---

### Task 6: Ticket actions and status machine

**Files:**
- Modify: `app/tickets/routes.py`, `app/models/ticket.py` (transition methods), `app/templates/tickets/detail.html` (action buttons per role/status)
- Create: `tests/test_ticket_actions.py`

**Interfaces:**
- Consumes: Task 5 routes/forms
- Produces on `Ticket` (each raises `InvalidTransition` when the current status disallows it; each appends a public system comment via `add_system_comment`):
  - `claim(agent: User) -> None` — `open → assigned`, sets `assignee`
  - `release(actor: User) -> None` — `assigned → open`, clears `assignee`
  - `assign_to(agent: User, actor: User) -> None` — sets `assignee` (from `open` also transitions to `assigned`)
  - `resolve(actor: User, note: str) -> None` — `assigned → resolved`, stores `resolution_note`, sets `resolved_at` (note required by form)
  - `reopen(actor: User) -> None` — `resolved → assigned` (any permitted role) or `closed → assigned` (admin only, enforced in route)
  - `close(actor: User) -> None` — `open|assigned|resolved → closed`, sets `closed_at`
  - Routes (all POST): `/tickets/<id>/claim`, `/release`, `/assign` (form `agent_id`), `/resolve` (form `resolution_note` required), `/reopen` (optional form `comment` body posted as a public comment), `/close`
  - Permission rules (route-level, 403 on violation): claim → agent/admin; release → assignee or admin; assign → admin; resolve → assignee or admin; reopen → requester/agent/admin from `resolved`, admin from `closed`; close → requester/assignee/agent/admin
  - On `InvalidTransition`: flash an error and redirect back to detail — state must not change

- [ ] **Step 1: Write the failing tests**

`tests/test_ticket_actions.py`:
- `test_claim_open_ticket` — status `assigned`, assignee set, system comment present
- `test_release_returns_to_open` — assignee cleared
- `test_admin_assigns_to_agent`
- `test_resolve_requires_note` — empty note → form error re-render, status unchanged
- `test_resolve_sets_note_and_resolved_at`
- `test_reopen_from_resolved_with_comment` — comment row added, status `assigned`
- `test_close_from_open_by_requester`
- `test_close_from_resolved_allowed` (plan addition)
- `test_claim_already_assigned_rejected` — flash error, assignee unchanged
- `test_user_cannot_claim_403`
- `test_non_assignee_agent_cannot_resolve_403`
- `test_reopen_closed_admin_only` — agent → 403; admin → status `assigned`
- `test_resolve_unassigned_open_rejected` — status unchanged

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ticket_actions.py -q`
Expected: FAIL

- [ ] **Step 3: Implement transition methods + routes + buttons**

System comment texts: `Claimed by {full_name}.`, `Released by {full_name}.`, `Assigned to {assignee} by {actor}.`, `Resolved by {actor}.`, `Reopened by {actor}.`, `Closed by {actor}.`. Detail template renders buttons from `status` + `current_user.role` (e.g., claim shows on `open` for agents; resolve shows on `assigned` for assignee/admin; reopen on `resolved` for requester/agents; close on `open|assigned|resolved` for permitted roles; assign form on `open|assigned` for admin). Resolve/reopen/close forms use `data-confirm` SweetAlert where destructive.

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: ticket status machine with claim, resolve, reopen, close"`

---

### Task 7: Queue view with filters

**Files:**
- Modify: `app/tickets/routes.py` (`tickets.queue`), `app/templates/tickets/queue.html`, `app/templates/base.html` (Queue link for agent/admin)
- Create: `tests/test_queue.py`

**Interfaces:**
- Consumes: Task 5/6 routes, `role_required`
- Produces: `tickets.queue` `GET /tickets/queue` (`role_required("agent", "admin")`, 403 for `user`); query params `status`, `category`, `priority`, `department_id`, `requester_id` (each optional; empty = no filter); template rows show number, subject, badges, requester, department, assignee, age, and a Claim button (agents, `open` tickets only)

- [ ] **Step 1: Write the failing tests**

`tests/test_queue.py`: `test_queue_requires_agent_role` (user → 403); `test_queue_lists_all_tickets` (agent sees every ticket number); `test_queue_filters` — seed distinct tickets; for each param assert the returned ticket-id set equals the expected subset (parametrize over the five params).

- [ ] **Step 2: Run tests to verify they fail** → run `.venv/bin/pytest tests/test_queue.py -q`, expect FAIL

- [ ] **Step 3: Implement queue route + template** — build filters as successive `if param:` query narrowing; newest first; template extends `base.html`.

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: agent queue with filters"`

---

### Task 8: Notifications

**Files:**
- Create: `app/notifications.py`, `app/templates/main/notifications.html`
- Modify: `app/main/routes.py` (notification routes), `app/templates/base.html` (bell + unread badge), `app/tickets/routes.py` (fire events)
- Create: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `Notification` model (Task 2)
- Produces in `app/notifications.py`:
  - `notify(recipient_ids: list[int], message: str, url: str, ticket: Ticket | None = None, exclude_id: int | None = None) -> None` — creates one row per recipient (skips `exclude_id`, skips ids already holding an identical unread row for the same `url`)
  - `unread_count(user: User) -> int`
  - Routes: `main.notifications` `GET /notifications` (own list), `main.notification_read` `POST /notifications/<int:notification_id>/read` (404 for others'), `main.notifications_read_all` `POST /notifications/read-all`
  - Event wiring in ticket routes: claim/assign → notify assignee; public comment → notify requester + assignee excluding actor; resolve/close → notify requester; reopen → notify assignee (or requester if actor is agent/admin and requester != actor); new pending registration → notify all admins. Internal comments → no notifications.

- [ ] **Step 1: Write the failing tests**

`tests/test_notifications.py`: `test_claim_notifies_assignee`; `test_public_comment_notifies_requester_and_assignee_not_actor`; `test_internal_comment_creates_no_requester_notification`; `test_status_change_notifies_requester`; `test_new_pending_registration_notifies_admins`; `test_unread_count_and_read_endpoints` (mark one → count drops; read-all → 0); `test_cannot_read_others_notifications` (404).

- [ ] **Step 2: Run tests to verify they fail** → `.venv/bin/pytest tests/test_notifications.py -q`, expect FAIL

- [ ] **Step 3: Implement helper, routes, badge, event wiring**

Bell in `base.html` navbar: link to `/notifications` with `<span>` badge shown when `unread_count(current_user) > 0` (import helper in template via context processor registered in the factory).

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: in-app notifications with unread badge"`

---

### Task 9: Admin area (dashboard, users, departments)

**Files:**
- Create: `app/admin/__init__.py`, `app/admin/routes.py`, `app/admin/forms.py`, `app/templates/admin/dashboard.html`, `app/templates/admin/users.html`, `app/templates/admin/user_form.html`, `app/templates/admin/departments.html`
- Modify: `app/__init__.py` (register blueprint), `app/templates/base.html` (Admin link)
- Create: `tests/test_admin.py`

**Interfaces:**
- Consumes: `role_required("admin")`, user/ticket models, `login` fixture
- Produces routes (all behind `role_required("admin")`, 403 otherwise):
  - `admin.dashboard` `GET /admin/` — renders `compute_dashboard_stats() -> dict` (pure function in `app/admin/routes.py`): counts `open`, `assigned`, `resolved_this_week`, `pending_users`, `by_category`, `by_priority`, `oldest_unassigned` (created_at or None), `stale_assignee` (count of tickets whose assignee status != active)
  - `admin.users` `GET /admin/users` with optional `?status=` filter; `admin.user_new` `GET/POST /admin/users/new`; `admin.user_edit` `GET/POST /admin/users/<int:user_id>/edit`; `admin.user_approve|reject|suspend|reactivate|reset_password` `POST /admin/users/<int:user_id>/{approve,reject,suspend,reactivate,reset-password}`
  - `admin.departments` `GET/POST /admin/departments`; `admin.department_delete` `POST /admin/departments/<int:department_id>/delete` (flash + no delete when users reference it)
  - Forms: `AdminUserForm` (username, full name, email, role, department, initial password on create), `ResetPasswordForm`, `DepartmentForm`
  - Semantics: approve → `active`; reject/suspend → `suspended`; create → `active` + `must_change_password=True` + `set_password(initial)`; reset-password → new hash + `must_change_password=True`

- [ ] **Step 1: Write the failing tests**

`tests/test_admin.py`: `test_agent_forbidden_from_admin` (403 on `/admin/`, `/admin/users`); `test_approve_pending_user` (status `active`, can now login); `test_reject_sets_suspended`; `test_create_user_active_with_forced_password_change` (can login, then redirected by forced-change gate); `test_edit_user_role_department`; `test_suspend_and_reactivate` (suspended cannot login); `test_reset_password_sets_flag_and_new_password_works`; `test_department_crud`; `test_delete_department_with_users_blocked`; `test_compute_dashboard_stats` (seeded fixture data → exact dict values); `test_dashboard_renders` (200).

- [ ] **Step 2: Run tests to verify they fail** → `.venv/bin/pytest tests/test_admin.py -q`, expect FAIL

- [ ] **Step 3: Implement admin blueprint, forms, templates, stats function**

Users page tabs via `?status=pending|active|suspended|all` (default `all`); pending tab lists Approve/Reject buttons (`data-confirm` on Reject). Destructive actions (suspend, reject, delete, reset) use SweetAlert confirms.

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: admin dashboard, user management, departments"`

---

### Task 10: `seed-admin` CLI command

**Files:**
- Create: `app/cli.py`, `tests/test_seed_admin.py`
- Modify: `app/__init__.py` (register CLI command `seed-admin`)

**Interfaces:**
- Consumes: `User` model, env vars `ADMIN_USERNAME`, `ADMIN_PASSWORD`
- Produces: `flask seed-admin` — if no `role == "admin"` user exists: read env (both required, else print error and exit code 1); create `User(username=..., role="admin", status="active", must_change_password=True)` with `set_password(ADMIN_PASSWORD)`; print created. If an admin already exists: print "admin already exists", exit 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_seed_admin.py` using `app.test_cli_runner().invoke(args=["seed-admin"])`: `test_seed_creates_admin_from_env` (monkeypatch both env vars → exit_code 0, admin row active + `must_change_password`); `test_seed_idempotent` (second invoke → exit_code 0, still exactly one admin); `test_seed_missing_env_fails` (env removed → exit_code 1, no user created).

- [ ] **Step 2: Run tests to verify they fail** → expect FAIL

- [ ] **Step 3: Implement `app/cli.py`** — `@click.command("seed-admin")` per the contract; register with `app.cli.add_command(seed_admin)` in the factory.

- [ ] **Step 4: Run tests to verify they pass, then full suite + lint, commit**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` → green
Then: `git add -A && git commit -m "feat: seed-admin cli command"`

---

### Task 11: Docker, README, AGENTS.md

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh`, `README.md`
- Modify: `.env.example` (finalize keys), `AGENTS.md` (replace the "minimal workspace" state with the real stack)

**Interfaces:**
- Consumes: everything above; `wsgi:app`; `flask db upgrade`; `flask seed-admin`
- Produces: runnable `docker compose up --build` on port 8000 with named volume `ttks_data:/data`

- [ ] **Step 1: Write Dockerfile, entrypoint, compose**

`Dockerfile`: `python:3.12-slim` base (3.15 may not have slim images yet — pin the newest slim tag that exists at build time), install `requirements.txt`, copy app, non-root user, `EXPOSE 8000`. `docker/entrypoint.sh` (executable, `sh`): `flask db upgrade && flask seed-admin && exec gunicorn -w 2 -b 0.0.0.0:8000 wsgi:app`. `docker-compose.yml`: service `web`, build `.`, ports `"8000:8000"`, volume `ttks_data:/data`, env `DATA_DIR=/data`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` (from `.env`), `restart: unless-stopped`.

- [ ] **Step 2: Verify compose config**

Run: `docker compose config -q`
Expected: exits 0 (valid YAML/schema)

- [ ] **Step 3: Build and smoke-test the stack**

Run: `docker compose up --build -d` then `curl -fsS -o /dev/null -w "%{http_code}" http://localhost:8000/auth/login`
Expected: `200`; then `docker compose down` (volume persists)
Expected: build fails only on network/registry issues — retry or report; app-level errors must be fixed here

- [ ] **Step 4: Write README.md**

Cover: what it is, roles, local dev (venv, `pip install -r requirements-dev.txt`, `cp .env.example .env`, `flask db upgrade`, `flask seed-admin`, `flask run`), verification commands (`.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/pytest -q`), Docker usage (`docker compose up --build`, port 8000, data in volume), and the four pinned env vars.

- [ ] **Step 5: Update AGENTS.md**

Replace the stale "minimal workspace" claims with: stack line, exact commands (venv path, pytest/ruff/flask), project layout one-liner (blueprints, models, migrations), and gotchas (WAL listener in `app/extensions.py`, env vars incl. `ADMIN_*`, CDN assets, no email — notifications in-app only, status machine lives on `Ticket` and raises `InvalidTransition`).

- [ ] **Step 6: Full suite + lint, commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` → green
Then: `git add -A && git commit -m "chore: docker deployment, readme, agent notes"`
