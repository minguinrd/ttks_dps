# Spanish as the default language — design

**Status:** awaiting approval · **Amends:** `2026-11-11-branding-i18n-design.md`
(anonymous-English clause, lines 28–29)

## Context

Today English is the fallback everywhere: anonymous pages (login, register,
pending, Google consent callbacks) render English, `get_locale()` falls back to
`"en"`, and every new account is created with `language="en"` — nobody ever
chose that; it was simply the only default. The office wants **Spanish to be
the default**: anonymous pages in Spanish, new accounts in Spanish, and
(existing) accounts moved to Spanish. English stays fully available as a
per-user profile choice. No browser-language detection either way.

## Decisions

1. **Default locale → `es`** (3 one-line changes):
   - `app/__init__.py` locale hook: anonymous/else branch `"en"` → `"es"`.
   - `app/i18n.py` `get_locale()`: in-request fallback `"en"` → `"es"`.
     The outside-application-context branch stays `"en"` so import-time key
     marking (`form` labels, `FORCED_PASSWORD_CHANGE_MESSAGE`) remains plain
     English source.
   - `app/templates/base.html`: `<html lang>` default `'en'` → `'es'`.
2. **New accounts → `es`**: `app/models/user.py` `language` `default` and
   `server_default` `"en"` → `"es"`. Registration, Google login, admin-created
   users and `seed-admin` all rely on the model default (no route sets it
   explicitly), so they all follow automatically.
3. **Existing accounts → `es`** (user decision): the migration rewrites all
   existing `language='en'` rows to `'es'`. The whole office sees Spanish
   immediately after deploy; anyone wanting English re-picks it in the profile.
4. **413-path locale fix (required for correctness):** move `csrf.init_app(app)`
   from *before* the locale hook to *after* it. Flask runs `before_request`
   hooks in registration order, and CSRF rejects oversized bodies while parsing
   the form — aborting before later hooks run — so `g.locale` was never set on
   the 413 path and error text fell back to the global default. Without the
   move, an **English** user would get Spanish oversize-upload errors (today's
   latent inverse: a Spanish user gets English). Flask-Login loads users lazily
   on `current_user` access, so registering the locale hook earlier is safe.
   Verified on a scratch build: `language=en` → `File too large (max 2 MB).`,
   `language=es` → `Archivo demasiado grande (máx. 2 MB).` on the CSRF 413 path.
5. **Tests stay English-explicit:** `user_factory` in `tests/conftest.py` pins
   `language="en"` — the existing suite asserts English text and now states
   its language explicitly instead of relying on the default.

## Migration

New Alembic revision on top of `7cee1007d919` (model + DDL stay in sync):

- `batch_alter_table("users")` → `alter_column("language", server_default="es")`
  (SQLite cannot ALTER a column default; batch recreate is the proven pattern —
  `env.py` already sets `PRAGMA foreign_keys=OFF`, and `44f3441fed14` is the
  template, including the `DROP TABLE IF EXISTS _alembic_tmp_users` guard).
- `UPDATE users SET language = 'es'` — flips every existing row.
- Downgrade reverses both (`server_default="en"`; row flip is not reversed —
  language is a per-user preference, no data value in `'es'`).

`tests/test_migrations.py` head pin moves from `7cee1007d919` to the new
revision SHA; extend `test_upgrade_with_child_rows` to assert the seeded
`alice` row ends up `language='es'` (backfill proof with child FK rows present).

## Test changes (measured: scratch run = 18 failed / 147 passed)

All 18 failures are legitimate expectation flips — every failing assertion
checks English text on a page that now renders Spanish (the strings are
already marked `_()` and present in `es.json`, so no catalog changes are
needed):

| Group | Tests | Flip |
|---|---|---|
| Anonymous flash/label assertions (13) | `test_admin.py::test_suspend_and_reactivate`; `test_auth.py` (`pending`, `suspended`, `wrong_password`, `duplicate_username`); `test_google_login.py` ×8 | expected English flash/label → Spanish catalog text |
| 413 oversize messages (2) | `test_branding.py::test_logo_oversize_rejected_with_csrf_enabled`, `test_profile.py::test_avatar_oversize_rejected_with_csrf_enabled` | `File too large (max 2 MB).` → `Archivo demasiado grande (máx. 2 MB).` (directly-created users get the new `es` default) |
| Forced-change flash (1) | `test_profile.py::test_avatar_oversize_forced_change_redirected_to_password` | pin that user `language="en"` — the test's purpose is the gate, not i18n; the shared `PINNED_FLASH` constant stays English. This also becomes the regression guard for decision 4: it only passes if the locale hook runs before CSRF |
| Anonymous-default tests (2) | `test_i18n.py::test_anonymous_pages_stay_english` → rename `test_anonymous_pages_default_to_spanish` (catalog Spanish present, English source absent on the anonymous login page); `test_i18n_completeness.py::test_confirm_dialog_chrome_translates` (anonymous block: `lang="es"` + Spanish confirm chrome; English-chrome coverage moves to a logged-in `language="en"` user) | inverted |

New coverage:

- Registration creates a user with `language='es'`.
- Migration backfill assertion (above).

## Files changed

`app/__init__.py`, `app/i18n.py`, `app/templates/base.html`,
`app/models/user.py`, new migration in `migrations/versions/`,
`tests/conftest.py`, the 18 flipped tests + 1 new test,
`tests/test_migrations.py`, `README.md` (Display language section), amendment
to `2026-11-11-branding-i18n-design.md` lines 28–29.

## Non-goals

- No browser-locale detection (unchanged).
- English is not removed or demoted — profile choice keeps working, and
  `user_factory`-driven tests keep proving the English path.
- No catalog additions (no new strings), no changes to user-generated content.
- No language field on registration/admin user forms.

## Verification gate

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
```

Expected: all tests green (147 kept + 18 flipped + new), ruff clean.
