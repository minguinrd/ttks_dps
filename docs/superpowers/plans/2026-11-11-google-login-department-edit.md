# Google Sign-In + Department Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add env-gated "Sign in with Google" (Authlib, pending-auto-create preserving admin approval) and complete the departments CRUD with rename.

**Architecture:** Two independent additions to the existing Flask app: a `department_edit` route mirroring the user-edit pattern, and an Authlib-backed Google OAuth flow in the `auth` blueprint with account matching by verified email then `google_sub`, gated entirely on config presence.

**Tech Stack:** Existing stack + `authlib` (new dependency), one Alembic migration.

**Spec:** `docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Pinned strings: pending refusal `Your account is awaiting admin approval.`; suspended refusal `This account has been suspended. Contact the administrator.`; Google failure (generic, all error paths) `Google sign-in failed. Please try again or use your username and password.`
- Google-created users: `status="pending"`, `role="user"`, `department_id=None`, random `password_hash` from `generate_password_hash(secrets.token_urlsafe(32))`, `google_sub` set, email stored lowercased
- Feature fully env-gated: `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` both non-empty → button shown and routes work; either missing → button hidden, `/auth/google` and `/auth/google/callback` flash the generic Google failure and redirect to login, password login unaffected
- Only Google-asserted `email_verified` truthy emails are trusted; `sub` matching takes precedence over email matching
- Department rename: admin-only, POST+CSRF, unique-name validation excluding the row itself
- Every task ends green: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` (if format check fails, run `.venv/bin/ruff format .` then re-check)
- No network I/O in tests: Google endpoints are stubbed at the Authlib client; `/auth/google` redirect assertion uses the URL Authlib builds locally
- Python here is 3.15: bump a dependency floor if install fails, keep the working pin

## Review Focus

1. **Unknown-email Google sign-in creating an `active` account (approval bypass)** → Task 2 `test_google_new_email_creates_pending_user` asserts `status == "pending"`, no session, redirect to `auth.pending`
2. **Pending/suspended accounts slipping past the Google gate** → Task 2 `test_pending_google_user_refused_on_login` and `test_suspended_google_user_refused` assert pinned message, no session
3. **Unverified email accepted as identity** → Task 2 `test_unverified_email_rejected` asserts generic failure, no user created, no link made
4. **Tampered/missing OAuth state on the callback** → Task 2 `test_state_mismatch_rejected` asserts generic failure and no user created
5. **Rename colliding with another department or with itself** → Task 1 `test_department_rename_duplicate_rejected` (other row's name → error, unchanged) and `test_department_rename_keep_own_name` (own name → succeeds)

---

### Task 1: Department rename (complete the CRUD)

**Files:**
- Modify: `app/admin/forms.py:63-71` (`DepartmentForm`), `app/admin/routes.py` (add route after `department_delete`), `app/templates/admin/departments.html` (Edit control per row)
- Test: `tests/test_admin.py`

**Interfaces:**
- Consumes: `DepartmentForm` with `validate_name` (currently rejects any existing name), `Department` model, `role_required("admin")`, existing flash+redirect conventions in `app/admin/routes.py`
- Produces: `DepartmentForm(edit_department: Department | None = None)` — duplicate check skips the row when `existing.id == edit_department.id` (same pattern as `AdminUserForm(edit_user=...)` at `app/admin/forms.py:12-14`); route `admin.department_edit` `GET/POST /admin/departments/<int:department_id>/edit`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin.py`:
- `test_department_rename` — seeded department; POST new name to `/admin/departments/<id>/edit` → 302 to `/admin/departments`, requery shows new name
- `test_department_rename_duplicate_rejected` — two departments; rename A to B's name → 200 re-render with `Department name already taken.` in HTML, A's name unchanged
- `test_department_rename_keep_own_name` — POST the department's current name → 302, no error (validator self-exclusion)
- `test_department_edit_forbidden_for_agent` — `user_factory(role="agent")` + `login` → POST edit → 403, name unchanged
- `test_department_edit_missing_404` — POST to id 999999 → 404

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_admin.py -q -k "department_rename or department_edit"`
Expected: FAIL (404 on missing route)

- [ ] **Step 3: Implement**

In `DepartmentForm.__init__`, accept `edit_department: Department | None = None` and in `validate_name` skip the rejection when `existing.id == edit_department.id`. Add `@admin_bp.route("/departments/<int:department_id>/edit", methods=["GET", "POST"])` → `department_edit(department_id: int)`: 404 via existing `_or_404`-style lookup if missing; on validate: update `name`, `flash("Department updated.", "success")`, redirect `admin.departments`; on GET or invalid: render the form pre-filled (new template `app/templates/admin/department_edit.html` extending `base.html`, one form, CSRF via `hidden_tag()`). In `departments.html` add an Edit link to `url_for("admin.department_edit", department_id=...)` beside the Delete control (Delete keeps its `data-confirm`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_admin.py -q`
Expected: PASS (existing department tests stay green — create path passes `edit_department=None`)

- [ ] **Step 5: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Then: `git add -A && git commit -m "feat: department rename completes admin crud"`

---

### Task 2: Google sign-in

**Files:**
- Modify: `requirements.txt` (add `authlib>=1.6`), `app/config.py` (two keys), `app/extensions.py` (`oauth = OAuth()`), `app/__init__.py` (init/register OAuth when configured; `google_enabled` context processor), `app/auth/routes.py` (two routes), `app/templates/auth/login.html` (button), `docker-compose.yml`, `.env.example`, `README.md`, `AGENTS.md` (env-var docs)
- Create: `app/auth/google_login.py`, `migrations/versions/*add_google_sub*.py` (generated), `tests/test_google_login.py`
- Modify: `app/models/user.py` (column) — migration via `.venv/bin/flask --app wsgi db migrate -m "add google_sub to users"` then `db upgrade`

**Interfaces:**
- Consumes: `login_manager`, `User` model, pinned refusal strings, `auth.login`/`auth.pending` routes, conftest fixtures (`app`, `client`, `user_factory`, `login`, `db_schema`)
- Produces:
  - `User.google_sub: str | None` (nullable, unique) + migration
  - Config keys `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (env, default `""`); context processor exposes `google_enabled: bool` (both non-empty)
  - `app/auth/google_login.py`: `class GoogleAuthError(Exception)` (sub/email conflict); `find_or_create_google_user(email: str, *, sub: str, name: str | None) -> tuple[User, bool]` — returns `(user, created)`; match by `google_sub` first, else case-insensitive email; on email match with a different `google_sub` raise `GoogleAuthError`; on link-less match set `google_sub`; on no match create the pending user per Global Constraints with username = email local part lowercased, colliding usernames suffixed `-2`, `-3`, …
  - Routes: `auth.google` `GET /auth/google` (config-gated; `google.authorize_redirect(url_for("auth.google_callback", _external=True))`); `auth.google_callback` `GET /auth/google/callback` (config-gated). The callback wraps the token exchange, userinfo parsing, **and** the `find_or_create_google_user` call in one `try/except Exception` → generic Google failure flash + redirect `auth.login` (this is what turns `GoogleAuthError` sub/email conflicts into the generic message instead of a 500 — plan-mandated third-party/error boundary). The status gate sits after the try.
  - Callback logic: `token = google.authorize_access_token()`; `userinfo = token.get("userinfo") or google.parse_id_token(token)`; require truthy `email_verified`, `sub`, `email` else generic failure; then `find_or_create_google_user`; then status gate — `pending` → pinned pending flash + redirect `auth.pending` (no session); `suspended` → pinned suspended flash + redirect `auth.login`; `active` → `login_user(user)` + redirect `url_for("main.index")` (same target as password login)
  - Test-local helper in `tests/test_google_login.py`: fixture `google_app` = `create_app` with `TESTING`, temp SQLite, `WTF_CSRF_ENABLED=False`, `GOOGLE_CLIENT_ID="test-client"`, `GOOGLE_CLIENT_SECRET="test-secret"`; `stub_google(monkeypatch, *, email, sub, name=None, email_verified=True)` monkeypatching `oauth.google.authorize_access_token` to return `{"userinfo": {...}}`
  - `login.html`: `{% if google_enabled %}` block below the password form — `<hr>` then an anchor to `url_for("auth.google")`, Bootstrap `btn btn-outline-secondary w-100`, label `Sign in with Google`

- [ ] **Step 1: Write the failing tests**

`tests/test_google_login.py`:
- `test_google_button_hidden_without_config` — default `app`, `GET /auth/login` → `Sign in with Google` absent
- `test_google_button_shown_with_config` — `google_app` client, `GET /auth/login` → button present with `href` containing `/auth/google`
- `test_google_login_redirects_to_google` — `google_app` client `GET /auth/google` → 302 with `Location` containing `accounts.google.com` and `redirect_uri` containing `/auth/google/callback`
- `test_google_new_email_creates_pending_user` — stubbed token (new email, sub `g-1`) → callback 302 to `/auth/pending`; user exists with `status=="pending"`, `role=="user"`, `department_id is None`, `google_sub=="g-1"`, email lowercased, username == email local part; session has no `user_id`
- `test_pending_google_user_refused_on_login` — user `status=="pending"` with email E + stub E → pinned pending message in response, no session
- `test_suspended_google_user_refused` — same with `status=="suspended"` → pinned suspended message, no session
- `test_existing_active_user_links_and_logs_in` — active user, email match, no `google_sub` → 302 to `/`, session set, `google_sub` stored
- `test_sub_preferred_over_email` — user linked to `sub-A`; stub returns `sub-A` with a different email → logs into that same user (no new user created)
- `test_unverified_email_rejected` — `email_verified=False` → generic Google failure message, no user row created
- `test_username_collision_gets_suffix` — existing user whose username equals the email local part → new pending user gets `<local>-2`
- `test_state_mismatch_rejected` — `google_app` client hits `/auth/google/callback` with no prior redirect session (real Authlib state check raises) → generic failure message, no user created
- `test_google_routes_without_config` — default `app` `GET /auth/google` and `GET /auth/google/callback` → generic failure flash + redirect to login, no 500

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_google_login.py -q`
Expected: FAIL (no routes / button / column)

- [ ] **Step 3: Install dependency + add column + config**

`requirements.txt`: add `authlib>=1.6`; `.venv/bin/pip install -r requirements-dev.txt`. `app/models/user.py`: `google_sub = db.Column(db.String(64), unique=True, nullable=True)` on `User`. `.env.example`: add `GOOGLE_CLIENT_ID=` and `GOOGLE_CLIENT_SECRET=` lines. Run `.venv/bin/flask --app wsgi db migrate -m "add google_sub to users"` then `db upgrade`; review the generated migration (single nullable unique column on `users`).

- [ ] **Step 4: Run tests to verify they fail differently**

Run: `.venv/bin/pytest tests/test_google_login.py -q`
Expected: still FAIL, now on missing routes/context (column exists)

- [ ] **Step 5: Implement config, OAuth wiring, helper, routes, button**

`app/config.py`: `GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")`, `GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")`. `app/extensions.py`: `oauth = OAuth()`. `create_app`: `oauth.init_app(app)`; when both values non-empty `oauth.register("google", server_metadata_url="https://accounts.google.com/.well-known/openid-configuration", client_kwargs={"scope": "openid email profile"})`; context processor returning `{"google_enabled": bool(id and secret)}`. `app/auth/google_login.py` per the Produces block (username collision loop appends `-2`, `-3`; `GoogleAuthError` on sub/email conflict). `app/auth/routes.py`: the two routes per Produces (broad `except Exception` at the OAuth boundary, plan-mandated). `login.html` button block per Produces.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_google_login.py -q`
Expected: PASS (all 12)

- [ ] **Step 7: Deploy/docs updates**

`docker-compose.yml`: add `GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}` and `GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET:-}` to the `web` service environment (empty default keeps the feature off when unset). `README.md`: one line under the env-var section noting the two optional Google vars and that the button appears only when both are set. `AGENTS.md` gotchas: extend the env-var line with `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (optional; gates the Google login button).

- [ ] **Step 8: Full gate + commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Then: `git add -A && git commit -m "feat: google sign-in with pending auto-create"`

---

## Post-conditions

- `docker compose up --build` with no Google env vars: login page identical to today, no button, everything green
- With `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` set: button appears; first sign-in with a new Gmail lands in the admin approval queue; approval makes Google login work; password login continues to work for everyone regardless
