# Design: Google Sign-In + Department Rename (ttks_dps)

Date: 2026-11-11
Status: awaiting human approval
Size: small change (short design; no builder check)

## Intent and why

Employees mostly have personal Gmail, so Google sign-in should be a convenient second door into the existing account system — never a bypass of the admin-approval rule the app is built on. Separately, the admin departments page can create and delete but not rename; completing the CRUD is a small consistency fix.

## Goals

- "Sign in with Google" button on the login page (shown only when Google credentials are configured)
- First Google sign-in with an unknown email → auto-create a `pending` user (lands in the admin approval queue exactly like self-registration; username derived from the email; random unusable password hash; `google_sub` stored; department left unset)
- Google sign-in with an email matching an existing account → log in (linking `google_sub` on first use; later logins match on `google_sub` first, then email, case-insensitive)
- Pending and suspended accounts get the same pinned refusal messages as password login
- Department rename: `GET/POST /admin/departments/<id>/edit` with unique-name validation, admin-only, POST+CSRF

## Non-goals

- No Workspace/domain restriction (accounts are personal Gmail)
- No password reset, account-unlinking UI, or multi-provider abstraction — Google only
- No changes to password login, registration, or approval flows

## Constraints

- Security: Authlib handles state (CSRF) param, token exchange, and ID-token signature verification; only Google-asserted `email_verified` emails are trusted; the callback never creates an active account
- Feature is env-gated: with `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` unset the button is hidden and login works exactly as today (no dead button, no crash, local dev unaffected)
- Department rename follows existing conventions: `role_required("admin")`, POST with CSRF, flash + redirect, duplicate name rejected with form error
- Existing pinned strings and status semantics untouched

## Approaches considered

1. **Hand-rolled OAuth2 redirect + token exchange** — no dependency, but reimplements state, nonce, signature verification, and error handling; rejected as unnecessary risk.
2. **Authlib Flask integration** — chosen: maintained standard library, one dependency, all security-critical parts delegated to it.
3. **Google Identity Services (GIS) library with a `credential` JWT posted from the browser** — fewer redirects, but moves verification into a JS flow and complicates the server-side session model; rejected.

## Decisions (the how)

- New dependency: `authlib` in `requirements.txt`
- Routes: `GET /auth/google` (redirect with state) and `GET /auth/google/callback` (verify, then the link/create logic above); both in the `auth` blueprint
- User model: add nullable unique `google_sub` column + a migration (schema-only change; `password_hash` gets a random `generate_password_hash(secrets.token_urlsafe(32))` for Google-created users)
- Username derivation: email local part lowercased; on collision append `-2`, `-3`, … (username is never used for Google login)
- If Google returns `email_verified=false` → flash a generic sign-in error, create nothing
- If an email is already linked to a different `google_sub` → flash generic error, no state change
- Config keys: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (env, optional); `.env.example` and Compose updated with commented/optional entries
- Login template: button below the password form, rendered only when configured
- Departments: `admin.department_edit` route reusing `DepartmentForm`; Edit button per row in `departments.html`
- Tests (pytest, following existing fixtures): unknown-email → pending created + no session + pending refusal message on retry; after fixture flips status → Google login works; existing active user links and logs in; suspended refused; state mismatch (tampered session) → error, nothing created; button hidden without config; rename happy path, duplicate rejected, `agent` gets 403
- Google flow is tested by stubbing Authlib's client (deterministic fixture returning verified email/sub) — no network in tests

## What's left to the builder

Exact form fields, template markup, callback error flashes beyond the pinned ones, migration contents — all consistent with the decisions above.

## Note

The pending integration menu from the first build (merge/PR/keep) remains open; work continues on `main` meanwhile.
