# Spanish Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Spanish the default display language — anonymous pages, new accounts, and existing accounts — while English remains a per-user profile choice.

**Architecture:** Three request-locale fallbacks flip from `"en"` to `"es"` (hook else-branch, `get_locale()` in-request default, `<html lang>` default), and `csrf.init_app` moves after the locale hook so the CSRF-413 path has a locale set. The `User.language` model default flips to `"es"` with an Alembic batch migration that also backfills every existing row. Tests pin `user_factory` to English explicitly; 18 measured expectation flips.

**Tech Stack:** Flask 3, Flask-SQLAlchemy, Flask-WTF (CSRF), Flask-Migrate/Alembic over SQLite, Jinja2, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-12-spanish-default-design.md` (approved; the plan argues from it)

## Global Constraints

- Verification gate after every task: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
- ruff: `line-length = 100`, lint rules `E,F,I` (E501 enforced); `docs/` excluded from ruff. Run `.venv/bin/ruff format <touched files>` after edits.
- No new dependencies. i18n is hand-rolled: `app/i18n.py`, catalog `app/locales/es.json`.
- Every user-visible literal marked `_()`; catalog keys are literal strings (never f-strings/concatenation); `tests/test_i18n_completeness.py` must pass.
- `get_locale()` outside an application context must keep returning `"en"` — import-time key marking stays English source.
- Baseline: 165 tests green at `de3752b` before this plan. Expected totals: Task 1 → **166 passed**, Task 2 → **167 passed**.
- Commit style: conventional (`feat:`, `docs:`). Design doc `docs/superpowers/specs/2026-11-12-spanish-default-design.md` is untracked and ships with Task 1's commit.

## Review Focus

1. **Import-time key marking must stay English.** Flipping `get_locale()`'s outside-context branch would bake Spanish into module-level constants (`FORCED_PASSWORD_CHANGE_MESSAGE`) and break English users' flashes. Pinned by Task 1's new `test_outside_app_context_stays_english`.
2. **The 413 path must honor the reader's own language, not just the default.** Pinned by Task 2's `test_avatar_oversize_forced_change_redirected_to_password` — user pinned `language="en"`, asserts the exact English flash through the CSRF-413 handler; fails again if the locale hook ever runs after CSRF.
3. **CSRF must still reject tokenless and oversized POSTs after `csrf.init_app` moves.** Pinned by the untouched `assert resp.status_code == 400` (no-token proof) at the top of `test_logo_oversize_rejected_with_csrf_enabled`, plus the full suite.
4. **The new migration recreates `users` while tickets/notifications reference it, and a leftover `_alembic_tmp_users` must not block it.** Pinned by Task 2's `alice`-language assertion in `test_upgrade_with_child_rows` (backfill proof with child FK rows present) and the existing `test_upgrade_recovers_from_leftover_temp_table` (both now run through the new head).
5. **No mixed-language anonymous pages** (spec anti-goal: half-translated UI). Pinned by Task 1's rewritten `test_anonymous_pages_default_to_spanish` — Spanish present AND English source absent; login/register pages verified to contain no unmarked English source.

---

### Task 1: Default locale → Spanish (anonymous + 413 path)

**Files:**
- Modify: `app/__init__.py` — extensions block (line 40) and the `set_request_locale` hook (lines 92-102)
- Modify: `app/i18n.py` — `get_locale()` (lines ~20-30)
- Modify: `app/templates/base.html:2`
- Modify: `tests/test_admin.py:154`
- Modify: `tests/test_auth.py:34,45,75,96`
- Modify: `tests/test_google_login.py:11-15,70`
- Modify: `tests/test_i18n.py` — remove line 7 import, replace lines 42-51, add one test
- Modify: `tests/test_i18n_completeness.py:88-93`
- Modify: `docs/superpowers/specs/2026-11-11-branding-i18n-design.md:28-29`
- Create: `docs/superpowers/specs/2026-11-12-spanish-default-design.md` (already written; commit it)

**Interfaces:**
- Consumes: `g.locale` set per request by `set_request_locale`; `translate()`/`_()` read it at call time; `SUPPORTED` locale set (all existing).
- Produces: in-request fallback `"es"` (anonymous requests and any path that skips the hook); `get_locale()` still returns `"en"` outside an app context; hook order **locale → CSRF → forced-password-change** (CSRF moves after the locale hook, stays before `force_password_change`); anonymous pages render Spanish; `<html lang>` defaults to `es`.

- [ ] **Step 1: Flip the 15 expectations (red first)**

`tests/test_admin.py:154` — the flash is a substring of the full suspended message; flip to the Spanish prefix (line fits: 75 chars):

```python
    assert "Esta cuenta ha sido suspendida." in resp.get_data(as_text=True)
```

`tests/test_auth.py` — four anonymous login/register flashes:

```python
    # line 34 — keep the split form (Spanish is >100 chars on one line):
    assert "Tu cuenta está pendiente de aprobación del administrador." in resp.get_data(
        as_text=True
    )
    # line 45 — replace the English string, keep the existing split:
    assert "Esta cuenta ha sido suspendida. Contacta con el administrador." in resp.get_data(
        as_text=True
    )
    # line 75:
    assert "Usuario o contraseña no válidos." in resp.get_data(as_text=True)
    # line 96:
    assert "El nombre de usuario ya está en uso." in resp.get_data(as_text=True)
```

`tests/test_google_login.py` — three module constants plus the button label (all five `GOOGLE_FAILURE_MESSAGE` usages flip with the constant):

```python
PENDING_MESSAGE = "Tu cuenta está pendiente de aprobación del administrador."
SUSPENDED_MESSAGE = "Esta cuenta ha sido suspendida. Contacta con el administrador."
GOOGLE_FAILURE_MESSAGE = (
    "No se pudo iniciar sesión con Google. Inténtalo de nuevo o usa tu "
    "nombre de usuario y contraseña."
)
```

Line 70: `assert "Iniciar sesión con Google" in html` (the negative assertion on line 61 stays). The `GOOGLE_FAILURE_MESSAGE` value must be implicit-concatenated as shown — formatters do not split string literals and the single line would exceed 100 chars.

`tests/test_i18n.py` — remove `from app import i18n` (line 7, becomes unused), replace `test_anonymous_pages_stay_english` (lines 42-51), and add the Review Focus pin after it:

```python
def test_anonymous_pages_default_to_spanish(client):
    # Spanish is the default locale: anonymous requests carry no stored
    # preference yet, so they render the catalog translation. Locale still
    # never comes from the browser.
    resp = client.get("/auth/login")

    html = resp.get_data(as_text=True)
    assert '<html lang="es">' in html
    assert "Iniciar sesión" in html
    assert "Sign in" not in html


def test_outside_app_context_stays_english():
    # Import-time key marking (module-level constants such as
    # FORCED_PASSWORD_CHANGE_MESSAGE) runs with no request locale: it must
    # stay English source so translation happens per request, not at import.
    assert translate("Sign in") == "Sign in"
```

(`translate` is already imported at line 9; the `monkeypatch` fixture and `_catalog_cache` patch are dropped — the real catalog now drives the page.)

`tests/test_i18n_completeness.py` — replace the anonymous block (lines 88-93), keeping the existing `language="es"` block above it; English coverage moves to an explicit English reader:

```python
    # Anonymous readers get the default locale (Spanish) — no stored
    # preference exists yet.
    anon_html = app.test_client().get("/auth/login").get_data(as_text=True)
    assert '<html lang="es">' in anon_html
    assert 'data-confirm-title="¿Estás seguro?"' in anon_html
    assert 'data-confirm-yes="Sí"' in anon_html
    assert 'data-confirm-cancel="Cancelar"' in anon_html

    # An explicit English choice keeps byte-identical English chrome.
    client.post("/auth/logout")
    en_user = user_factory(username="en-confirm", language="en")
    login(client, en_user)
    en_html = client.get("/notifications").get_data(as_text=True)
    assert '<html lang="en">' in en_html
    assert 'data-confirm-title="Are you sure?"' in en_html
    assert 'data-confirm-yes="Yes"' in en_html
    assert 'data-confirm-cancel="Cancel"' in en_html
```

- [ ] **Step 2: Run the subset to verify exactly these 15 fail**

Run: `.venv/bin/pytest tests/test_admin.py tests/test_auth.py tests/test_google_login.py tests/test_i18n.py tests/test_i18n_completeness.py -q`
Expected: **15 failed** — `test_suspend_and_reactivate`, `test_pending_user_cannot_login`, `test_suspended_login_refused`, `test_wrong_password_rejected`, `test_duplicate_username_rejected`, `test_google_button_shown_with_config`, `test_google_redirect_failure_returns_generic_error`, `test_pending_google_user_refused_on_login`, `test_suspended_google_user_refused`, `test_unverified_email_rejected`, `test_state_mismatch_rejected`, `test_google_routes_without_config`, `test_google_sub_conflict_refused`, `test_anonymous_pages_default_to_spanish`, `test_confirm_dialog_chrome_translates`. New `test_outside_app_context_stays_english` passes. No other failures.

- [ ] **Step 3: Implement the three locale flips + CSRF reorder**

`app/__init__.py` — remove `csrf.init_app(app)` from the extensions block (line 40; the block becomes `db`, `migrate`, `login_manager`, `oauth`, …), then replace the hook and insert the CSRF init immediately after it (before `@app.before_request force_password_change`):

```python
    @app.before_request
    def set_request_locale():
        # Display language for this request (app.i18n reads g.locale). Anonymous
        # users get the default locale — no browser detection. Static files skip
        # the work entirely; nothing template-rendered ever runs for them.
        if request.endpoint == "static":
            return
        if current_user.is_authenticated and current_user.language in SUPPORTED:
            g.locale = current_user.language
        else:
            g.locale = "es"

    # CSRF must be initialised AFTER the locale hook: Flask runs before_request
    # hooks in registration order, and CSRF rejects oversized bodies (413) while
    # parsing the form — before later hooks run. Registering it here keeps
    # g.locale set for the 413 error handler's translated messages.
    csrf.init_app(app)
```

`app/i18n.py` — `get_locale()` becomes:

```python
def get_locale() -> str:
    """Locale for the current request (``"es"`` when none was set).

    Also returns ``"en"`` outside an application context, so import-time key
    marking (e.g. form labels) stays plain English source.
    """
    try:
        return getattr(g, "locale", "es")
    except RuntimeError:  # pragma: no cover - only hit outside an app context
        return "en"
```

`app/templates/base.html` line 2: `<html lang="{{ g.locale | default('es') }}">`.

- [ ] **Step 4: Run the subset to verify it passes**

Run: `.venv/bin/pytest tests/test_admin.py tests/test_auth.py tests/test_google_login.py tests/test_i18n.py tests/test_i18n_completeness.py -q`
Expected: all pass.

- [ ] **Step 5: Amend the branding-i18n spec**

`docs/superpowers/specs/2026-11-11-branding-i18n-design.md` lines 28-29 become:

```markdown
- Anonymous pages (login, register, pending) display in the default locale —
  Spanish since `2026-11-12-spanish-default-design.md`, which supersedes the
  original English default. No stored preference exists yet;
  browser-language detection is out of scope.
```

- [ ] **Step 6: Full gate**

Run: `.venv/bin/ruff format app tests && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: **166 passed**, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py app/i18n.py app/templates/base.html tests/test_admin.py \
  tests/test_auth.py tests/test_google_login.py tests/test_i18n.py \
  tests/test_i18n_completeness.py \
  docs/superpowers/specs/2026-11-11-branding-i18n-design.md \
  docs/superpowers/specs/2026-11-12-spanish-default-design.md \
  docs/superpowers/plans/2026-11-12-spanish-default.md
git commit -m "feat: spanish as the default display locale"
```

---

### Task 2: Accounts default to Spanish (model + migration + backfill)

**Files:**
- Modify: `tests/conftest.py` — `user_factory` (line ~53)
- Modify: `tests/test_branding.py:338`
- Modify: `tests/test_profile.py:236,263`
- Modify: `tests/test_auth.py` — new test after `test_duplicate_username_rejected` (line 100)
- Modify: `app/models/user.py` — `language` column
- Create: `migrations/versions/<REV>_spanish_default.py` (down_revision `7cee1007d919`)
- Modify: `tests/test_migrations.py:67,73-76`
- Modify: `README.md:15-22`

**Interfaces:**
- Consumes: Task 1's hook order (stored `language` drives `g.locale` on every path including CSRF-413); `user_factory(role, status, password, **overrides)` (overrides flow into `User(...)`).
- Produces: `User.language` default `"es"` (ORM `default` + DDL `server_default`); every pre-existing row `'es'`; Alembic head `<REV>` with `down_revision = "7cee1007d919"`; `user_factory` pins `language="en"`.

- [ ] **Step 1: Pin `user_factory` to English (guard for the model flip)**

`tests/conftest.py` — add after the `username` setdefault:

```python
        overrides.setdefault("language", "en")
```

with the comment: `# Tests that assert English text pin the language explicitly; the app default is Spanish.`

Run: `.venv/bin/pytest -q` → Expected: **166 passed** (no behavior change yet — the model default is still `"en"`).

- [ ] **Step 2: Flip the three remaining expectations (red)**

`tests/test_branding.py:338` and `tests/test_profile.py:236` (both currently `assert "File too large (max 2 MB)." in resp.get_data(as_text=True)`):

```python
    assert "Archivo demasiado grande (máx. 2 MB)." in resp.get_data(as_text=True)
```

`tests/test_profile.py:263` — pin the directly-created user to English (the test asserts the exact English flash; it doubles as the Review Focus proof that the 413 handler honors the reader's language):

```python
        user = User(
            username="csrf-flagged",
            status="active",
            must_change_password=True,
            language="en",
        )
```

New test in `tests/test_auth.py`, directly after `test_duplicate_username_rejected` (payload mirrors it; register returns 302 to `/auth.pending`):

```python
def test_new_user_defaults_to_spanish(client, app):
    resp = client.post(
        "/auth/register",
        data={
            "username": "nuevo",
            "password": "pass12345",
            "confirm": "pass12345",
            "full_name": "Nuevo Usuario",
            "email": "nuevo@example.com",
            "department": "",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username="nuevo"))
        assert user.language == "es"
```

Run: `.venv/bin/pytest tests/test_branding.py::test_logo_oversize_rejected_with_csrf_enabled tests/test_profile.py tests/test_auth.py::test_new_user_defaults_to_spanish -q`
Expected: **3 failed** — the two oversize tests (pages still English) and `test_new_user_defaults_to_spanish` (default still `"en"`). `test_avatar_oversize_forced_change_redirected_to_password` passes (pinned).

- [ ] **Step 3: Flip the model default**

`app/models/user.py`:

```python
    language = db.Column(db.String(5), nullable=False, default="es", server_default="es")
```

Run: the same subset command from Step 2 → Expected: all pass.

- [ ] **Step 4: Write the migration (red on the head pin)**

Generate a revision id: `.venv/bin/python -c "import uuid; print(uuid.uuid4().hex[:12])"` → call it `<REV>`.

Create `migrations/versions/<REV>_spanish_default.py` (template: `44f3441fed14_add_user_language.py`):

```python
"""spanish default language

Revision ID: <REV>
Revises: 7cee1007d919
Create Date: ...

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "<REV>"
down_revision = "7cee1007d919"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite DDL is non-transactional: an interrupted prior run can leave the
    # batch temp table behind and block every retry with
    # "table _alembic_tmp_users already exists". Clear any leftover first.
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_users")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "language",
            existing_type=sa.String(length=5),
            existing_nullable=False,
            existing_server_default="en",
            server_default="es",
        )

    # Spanish is the default: existing accounts never chose English — it was
    # simply the only default — so move everyone over.
    op.execute("UPDATE users SET language = 'es'")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "language",
            existing_type=sa.String(length=5),
            existing_nullable=False,
            existing_server_default="es",
            server_default="en",
        )
    # Data is deliberately not flipped back: language is a per-user preference.
```

Run: `.venv/bin/pytest tests/test_migrations.py -q`
Expected: **1 failed** — `test_upgrade_with_child_rows` fails at the old head pin `7cee1007d919` (line 76), which also proves the new migration itself ran to completion. `test_upgrade_recovers_from_leftover_temp_table` **passes**: it upgrades through the new migration with a leftover `_alembic_tmp_users` present (Review Focus 4).

- [ ] **Step 5: Move the head pin and prove the backfill**

`tests/test_migrations.py` — line 67 comment becomes `# to head: add google_sub + settings + user language + notification keys + spanish default`; line 76 becomes `assert version == "<REV>"` (the generated id); after the user-count assertion (line 73) add:

```python
    alice_row = conn.execute("SELECT language FROM users WHERE username='alice'").fetchone()
    assert alice_row[0] == "es"
```

Run: `.venv/bin/pytest tests/test_migrations.py -q` → Expected: both pass (the `alice` row was seeded pre-backfill with child FK rows present, so this proves the batch recreate + `UPDATE`).

- [ ] **Step 6: README**

`README.md` — the Display language section (lines 15-22) opens:

```markdown
## Display language

Spanish is the default: anonymous pages and new accounts render in Spanish,
and existing accounts were switched over by the `spanish default language`
migration. Each user picks English or Spanish on their profile page
(`/profile`); the choice applies to every page from the next request on. New
```

(keep the remainder of the paragraph unchanged).

- [ ] **Step 7: Full gate**

Run: `.venv/bin/ruff format app tests migrations && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: **167 passed**, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add app/models/user.py migrations/versions/<REV>_spanish_default.py \
  tests/conftest.py tests/test_branding.py tests/test_profile.py \
  tests/test_auth.py tests/test_migrations.py README.md
git commit -m "feat: spanish default language for user accounts"
```
