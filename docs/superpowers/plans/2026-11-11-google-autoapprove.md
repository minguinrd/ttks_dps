# Google Auto-Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accounts created by Google sign-in start `active` (no admin approval), while password registration keeps its approval gate.

**Architecture:** One-line behavior change in the Google account-matching module (`status="active"` on creation) plus reworded admin notification; the callback's status gate is untouched, so pre-existing `pending` accounts (e.g. password registrants) are still refused — the self-approval loophole stays closed. Tests that pinned the old `pending` creation flip to the new expectation; docs are amended to match.

**Tech Stack:** Flask + Flask-SQLAlchemy + pytest (existing app, no new dependencies).

**Spec:** `docs/superpowers/specs/2026-11-11-google-autoapprove-design.md` (binding); amends `docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md`.

## Global Constraints

- **No new dependencies.**
- **Auto-approve on creation only:** `find_or_create_google_user` may set `status="active"` only on the branch that creates a user; existing-user branches (google_sub match, email match/link) never change `status`.
- **Loophole must stay closed:** a pre-existing `pending` account (password-registered) hitting the Google callback is refused with the pinned `PENDING_MESSAGE` and gets no session — pinned by the existing test `test_pending_google_user_refused_on_login`, which must stay green.
- **Notification copy (exact):** `f"New user {user.username} registered via Google."` to all admins, url `/admin/` — password-registration copy (`is awaiting approval.`) untouched.
- **Pinned strings untouched:** `PENDING_MESSAGE`, `SUSPENDED_MESSAGE`, `GOOGLE_FAILURE_MESSAGE` (`app/auth/routes.py:12-18`).
- Role stays `user`, department stays unset for Google-created accounts.
- Every step ends green: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q` (baseline: 134 passed at `f2d7aab`).
- ruff excludes `docs/`; pytest has `pythonpath = ["."]`.

## Review Focus

Inputs/behaviors the spec implies but this change's flipped tests don't each pin — owned by Task 1:

1. **Self-approval loophole:** register with password (→ `pending`), then sign in via Google — must still be refused, not activated. Pinned by the existing `test_pending_google_user_refused_on_login`; Task 1 Step 2 adds a comment naming it as the loophole lock so a future editor can't delete it as "stale pending test".
2. **Old pending Google users (deployments predating this change):** a `pending` user created by the old code retrying Google must be refused, not silently activated — same status-gate test covers it; Step 2's comment says so.
3. **Notification drift:** the retry path must not re-notify after the copy/rename changes — `test_google_retry_does_not_notify_again` (renamed in Step 1) keeps its mark-read-then-retry assertion.
4. **Docs contradiction:** the old spec literally says "the callback never creates an active account" — Step 4 amends it; a reviewer should grep both spec files for `pending`/`never creates an active` after Step 4 and find no unamended claim.
5. **Password-registration regression:** register → pending → approval flow must be byte-identical — existing `tests/test_register.py` / `tests/test_auth.py` stay green through Step 3 (no edits allowed to them).

---

### Task 1: Google-created accounts are active

**Files:**
- Modify: `app/auth/google.py:14-67` (creation branch: status, notification copy, docstring/comments)
- Modify: `tests/test_google_login.py` (flip 3 tests, rename 2, comment on 1)
- Modify: `docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md` (amend pending claims)
- Modify: `README.md` (login note)
- Create: `docs/superpowers/specs/2026-11-11-google-autoapprove-design.md` (already written this session; commit it)

**Interfaces:**
- Consumes: `find_or_create_google_user(email: str, *, sub: str, name: str | None) -> tuple[User, bool]` and the callback status gate in `app/auth/routes.py:114-121` — both unchanged in signature/behavior for existing users.
- Produces: the same `find_or_create_google_user` with creation now yielding `status="active"`; notification copy `New user {username} registered via Google.`. No later task.

- [ ] **Step 1: Flip the pinned tests (RED)**

In `tests/test_google_login.py`:

1. Rename `test_google_new_email_creates_pending_user` → `test_google_new_email_creates_active_user` and change its assertions to:

```python
def test_google_new_email_creates_active_user(app, google_app, db_schema, monkeypatch):
    stub_google(monkeypatch, email="New.Person@Example.com", sub="g-1", name="New Person")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="new.person@example.com"))
        assert user is not None
        assert user.status == "active"
        assert user.role == "user"
        assert user.department_id is None
        assert user.google_sub == "g-1"
        assert user.username == "new.person"
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == str(user.id)
```

2. In `test_username_collision_gets_suffix`: `assert created.status == "pending"` → `assert created.status == "active"` (line ~212).
3. In `test_google_new_user_notifies_admins`: expected message → `assert rows[0].message == "New user new.person registered via Google."` (line ~250); keep every other assertion.
4. Rename `test_pending_google_retry_does_not_notify_again` → `test_google_retry_does_not_notify_again` and update its comments only: line ~261 `# first sign-in creates the pending user` → `# first sign-in creates the user`; line ~271 `# still-pending user retries Google` → `# returning user retries Google`. Assertions unchanged (the mark-read-then-retry structure must stay).
5. In `test_pending_google_user_refused_on_login` add a comment above the function:

```python
# Loophole lock: a password-registered PENDING account must stay refused at the
# Google callback — never activated by signing in with Google. Also covers
# pending users created by the pre-auto-approval code. Do not delete as stale.
```

Do **not** edit any other test file.

- [ ] **Step 2: Run flipped tests to verify they fail**

Run: `.venv/bin/pytest tests/test_google_login.py -q`
Expected: FAIL — `test_google_new_email_creates_active_user` (Location `/auth/pending` ≠ `/`), `test_username_collision_gets_suffix` (`pending` ≠ `active`), `test_google_new_user_notifies_admins` (old message). Others pass. This is RED.

- [ ] **Step 3: Implement the auto-approve in `app/auth/google.py`**

Three edits in the creation path only (lines 14-67):

1. `status="pending"` (line 48) → `status="active"`.
2. Notification message (line 63) → `f"New user {user.username} registered via Google."`; update the comment above it (lines 57-59) to: admins keep visibility of newcomers even though approval is gone; existing users retrying Google never reach this branch.
3. Rewrite the docstring (lines 15, 21-23): "creating an active user when new" and replace the pending-approval sentences with: Google proved the account, so new users are born `active` and land in the app immediately; all admins get a `registered via Google` notification for visibility; pre-existing accounts keep their status (pending stays refused by the callback).

No change to `app/auth/routes.py` — the status gate at lines 114-121 already handles every case correctly.

- [ ] **Step 4: Run the Google test file to verify it passes**

Run: `.venv/bin/pytest tests/test_google_login.py -q`
Expected: PASS — all tests in the file, including `test_pending_google_user_refused_on_login` (loophole still closed) and `test_google_retry_does_not_notify_again`.

- [ ] **Step 5: Run the full suite (password flows untouched)**

Run: `.venv/bin/pytest -q`
Expected: 134 passed — `tests/test_register.py` and `tests/test_auth.py` green with zero edits.

- [ ] **Step 6: Amend the old spec + README**

1. `docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md`:
   - After line 4 (`Status: awaiting human approval`) add: `Amended 2026-11-11: Google-created accounts are now auto-approved — see 2026-11-11-google-autoapprove-design.md.`
   - Line 9 (intent): replace `never a bypass of the admin-approval rule the app is built on` with `approval still gates password signups; Google signups are auto-approved (amended 2026-11-11)`.
   - Line 14: `auto-create a `pending` user (lands in the admin approval queue exactly like self-registration;` → `auto-create an `active` user (Google proves the account, so no approval — amended 2026-11-11;` keep the rest of the parenthetical (username derivation, random password, `google_sub`, department unset).
   - Line 16: append `(pre-existing pending accounts are still refused)`.
   - Line 27: `the callback never creates an active account` → `the callback never activates a pre-existing account; accounts it creates are active (amended 2026-11-11)`.
   - Line 49: `unknown-email → pending created + no session + pending refusal message on retry` → `unknown-email → active created + session; pre-existing pending refused on retry`.
2. `README.md`: in the Google row of the env table (line 83) or the login section, append: `Google sign-in creates an active account immediately (no admin approval); password registration still requires approval.`

Grep check: `grep -n "pending\|never creates an active" docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md` — every remaining `pending` must refer to *pre-existing/password* pending accounts.

- [ ] **Step 7: Full gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: clean + 134 passed.

- [ ] **Step 8: Commit**

```bash
git add app/auth/google.py tests/test_google_login.py README.md docs/superpowers/specs/
git commit -m "feat: google-created accounts skip admin approval"
```
