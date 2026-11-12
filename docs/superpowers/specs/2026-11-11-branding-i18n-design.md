# Design: Branding Module + Per-User Display Language (ttks_dps)

Date: 2026-11-11
Status: draft — builder check pending, then human approval

## Intent and why

Two sibling needs for this internal tool: (1) the identity is currently welded
into `base.html` ("Tech Support" title + navbar text, stock Bootstrap blue) —
admins should be able to rename the site, set a logo, and pick an accent color
from the admin panel without touching code; (2) the office has Spanish-speaking
staff — every user should be able to pick English or Spanish for the display
language, and get a *fully* translated UI, not a half-translated one.

## Goals

- **Branding (admin-editable):** site name, logo (file upload), accent color —
  stored in the database, edited on an admin-only settings page, applied live
  everywhere (browser tab, navbar, login page, primary buttons/links/active
  nav). Text brand remains the fallback until a logo is uploaded; a "remove
  logo" action reverts to it.
- **Language (per-user):** each user picks `English` or `Spanish` on their
  profile page; choice is stored on the account and applies to every page they
  see — templates, flash messages, form labels, validation errors, status /
  category / priority / role badges, enum choice lists, and notifications.
- **Everything visible is translatable:** admin pages included. User-generated
  content (ticket subjects, comments, descriptions, names) is never translated.
- Anonymous pages (login, register, pending) display in the default locale —
  Spanish since `2026-11-12-spanish-default-design.md`, which supersedes the
  original English default. No stored preference exists yet;
  browser-language detection is out of scope.

## Non-goals / anti-goals

- No machine translation of user-generated content.
- No browser-locale detection for anonymous visitors.
- No RTL languages, no third language, no date/number localization (naive UTC
  timestamps render as today).
- No new dependencies (any approach requiring one is rejected).
- Anti-goal: a half-translated UI. A Spanish user seeing English buttons under
  Spanish text is worse than no localization — the completeness test (below)
  is the guard.
- No theme presets or multi-tenant white-labeling — one branding per deploy.

## Constraints

- State-changing routes: POST + CSRF, `role_required("admin")` for branding.
- Logo stored in `DATA_DIR/branding/` (the Docker volume) — never in the image
  tree — validated type + size, served by a public route (the login page needs
  it pre-auth), replaced/deleted files cleaned up.
- Accent color validated as `#rrggbb` before storage; injected as a CSS custom
  property, never as raw unsanitized markup.
- Two schema changes need Alembic migrations (`settings` table,
  `users.language`; plus notification localization columns — see Decisions).
- All existing tests stay green: source strings remain English, and the
  legacy `notifications.message` column keeps being written, so English
  assertions are unaffected.
- `migrations/env.py` FK-off fix must not be regressed (existing gotcha).

## Approaches considered

**Display-language mechanism:**

1. **Hand-rolled i18n module (CHOSEN — user picked):** `app/i18n.py` with a
   `_("...")` helper, one JSON catalog (`app/locales/es.json`), locale loaded
   per request from the authenticated user, `_` exposed to Jinja and used in
   Python. ~50 lines of machinery, zero dependencies, diffable catalogs,
   trivially testable. Trade-off: no extraction tooling — a missed mark leaks
   English, caught by the completeness test.
2. **Flask-Babel (rejected):** idiomatic gettext `.po`/`pybabel` workflow with
   pluralization and `ngettext` — but two new dependencies, a compile step in
   the Docker build, and machinery this exactly-two-language tool never uses.

**Branding storage:**

1. **`settings` key-value table (CHOSEN):** `Setting(key, value)` rows, read
   per request through a context processor, cached for the request. Extensible
   (future keys), standard pattern, one small migration.
2. **Env vars / config file (rejected):** the user explicitly wants
   admin-editable at runtime, no redeploy.
3. **Dedicated `branding` single-row table (rejected):** same result, less
   extensible, no gain.

## Decisions (the how)

### Branding

- **Model:** `Setting` with `key` (str, primary key) and `value` (text).
  Keys: `site_name`, `logo_file` (filename under `DATA_DIR/branding/`),
  `accent_color`. Missing key ⇒ default (`"Tech Support"`, no logo,
  `#0d6efd` — current Bootstrap primary).
- **Admin page:** `GET/POST /admin/branding` in the admin blueprint
  (`role_required("admin")`, CSRF form) — fields: site name (required,
  ≤ 100 chars), accent color (text field, `#rrggbb` pattern), logo upload
  (optional; PNG/JPEG/SVG; ≤ 2 MB), plus a "Remove logo" POST action.
  Flash + redirect on save, form errors inline — same conventions as
  departments.
- **Logo service route:** `GET /branding/logo` — public (no login), serves
  the stored file with `send_file`, 404 when absent. Lives in the `main`
  blueprint (already public-ish) or its own tiny public endpoint; the plan
  pins the exact home.
- **Application:** a context processor injects `branding` (site_name,
  has_logo, logo_url, accent_color) into every template. `base.html`:
  `<title>{{ branding.site_name }}`, navbar-brand renders `<img>` when a logo
  exists else the site name text, and a `<style>` block sets
  `:root { --brand-accent: ... }` plus rules mapping that variable onto the
  navbar background, `btn-primary`, active nav items, and links (a small,
  explicit rule set — not a wholesale Bootstrap override).
- **Upload handling:** `werkzeug` secure filename is insufficient alone —
  generate the stored filename ourselves (`logo.<ext>` where ext comes from a
  whitelist), reject everything else, write under `DATA_DIR/branding/`
  (created on demand), delete any previous file on replace/remove.

### Display language

- **Column:** `users.language` — `NOT NULL DEFAULT 'en'`, CHECK-style
  validation in the app to `("en", "es")`. Migration.
- **Catalog:** `app/locales/es.json` — flat map `source-English-string →
  Spanish`. No `en.json`: English *is* the source string; `_()` falls back to
  returning the source when a key is missing (English page either way).
  Catalog loaded lazily, module-level cached.
- **Runtime:** `app/i18n.py` exposes `SUPPORTED`, `get_locale()` (reads `g`,
  set by a `before_request` hook: authenticated user's `language` if valid,
  else `"en"`), and `_()` (translate `get_locale()`-scoped). `_` is injected
  as a Jinja global; Python code imports `_` from `app.i18n`.
- **Marking convention:** templates mark every user-visible literal:
  `{{ _("Queue") }}`. Parameterized strings translate first, format second:
  `_("New user {name} registered.").format(name=...)` — keys are always
  literals (catalog lookup), never f-strings.
- **Forms:** WTForms labels/errors stay English in Python. Templates render
  labels through a new macro (in `app/templates/macros/`) that emits
  `<label for="{{ field.id }}">{{ _(field.label.text) }}</label>`; validation
  errors render as `{{ _(error) }}` through a translate-error helper: exact
  catalog lookup first; on a miss, keys containing `{placeholders}` (e.g.
  `"Field must be between {min} and {max} characters long."`) are converted
  to regexes, matched against the concrete English error, and re-formatted
  with the captured values into the Spanish template — so parameterized
  validator messages (Length, EqualTo, NumberRange) translate without
  touching any form code. The `es.json` catalog includes the common
  Flask-WTF/WTForms messages (required, invalid email, CSRF, etc.).
- **Badges/enums:** the existing `macros/badges.html` translates the fixed
  label words (status, priority, category, role) through `_()` — one choke
  point covers every table and list. **Department names pass through
  untranslated:** they are admin-entered data (like ticket subjects), not
  fixed enum labels; the badge renders the raw value.
- **Selector:** profile page gains a language `SelectField` (English/Spanish),
  POST + CSRF, saved to `users.language`; takes effect on the next render
  (`before_request` reads it fresh each request). Existing profile
  conventions (flash + redirect) apply.
- **Notifications (the stored-string seam):** notification rows store final
  English sentences today, which can't be re-translated per reader. Decision:
  add nullable `message_key` (literal catalog key) and `params` (JSON text)
  columns to `notifications`; new notifications write **both** the legacy
  `message` (backward compat, English fallback) and key+params; the
  notifications template renders `_(key).format(**params)` when `message_key`
  is set, else the raw stored message (legacy rows). No backfill.
- **Completeness test (the anti-half-translation guard):** a test regex-scans
  all `app/templates/**/*.html` and `app/**/*.py` for `_("...")` literals and
  asserts every one exists in `es.json`; plus asserts no stale keys (every
  catalog key is found in the source). Missing translation = red build.

## What's left to the builder

Exact template-by-template marking list, the CSS rule set for the accent
variable, form/macro markup details, migration contents, exact test names,
upload route wiring, and README/AGENTS.md/.env.example documentation updates
(no new env vars — docs note the admin page and profile selector instead).

## Note

Depends on nothing in-flight; work continues on `main` (established consent).
