# Design: Google sign-ins skip admin approval

**Date:** 2026-11-11
**Status:** Short design (user-approved approach; awaiting design-doc approval)

## Problem

Users who sign up with Google currently land in the approval queue like
password registrants. Google sign-in already proves the account is real, so the
admin has no use for that gate — the owner wants Google-created accounts to
start usable immediately.

## Approaches considered

1. **Google accounts auto-approved; password accounts still gated (chosen).**
   Matches the owner's reasoning: Google proves identity, so the approval queue
   keeps its purpose only for password signups.
2. Keep approval for everyone (status quo) — rejected: the owner explicitly
   wants Google signups ungated.
3. Auto-approve every signup — rejected: keeps the open door on the password
   form, which has no identity proof at all.

## Decision

Accounts **created by Google sign-in** are born `status="active"`. The user
lands straight in the app with a session. Password self-registration keeps the
pending/approval flow unchanged.

## Design

### Auto-approve on creation only

`find_or_create_google_user` (`app/auth/google.py`) creates new users with
`status="active"` instead of `"pending"`.

**Password-registered pending accounts stay gated** even if that person later
signs in with Google: the auto-approve applies only when the account is created
by the Google callback. Otherwise anyone could register with a password, click
the Google button, and approve themselves — gutting the approval flow. Concretely,
the callback's pending-refusal branch (`app/auth/routes.py`) keeps refusing
*pre-existing* pending accounts; only freshly created ones are active.

### Admin notification

The "new user registered" admin notification fires for Google-created users
with reworded copy: `New user {username} registered via Google` — visibility of
newcomers is kept even though approval is gone.

### Tests

- The existing "new Google email" test (`tests/test_google_login.py`) flips:
  expects an active session (no approval) + the reworded notification.
- Existing password-registration tests (`tests/test_register.py`,
  `tests/test_auth.py`) untouched — the pending path must not regress.
- Add a covering test: a pre-existing **pending** password account signing in
  via Google is still refused (the self-approval loophole stays closed).

### Docs

- `docs/superpowers/specs/2026-11-11-google-login-department-edit-design.md`
  amended: the "approval applies to signups with a new email" section and the
  status matrix updated to say Google-created accounts are active immediately.
- `README.md` login section: note that Google sign-in creates an active
  account without admin approval.

### Non-goals

- No role changes (Google users still start as `user`).
- No change to password registration or the admin approval page.
- No migration (production has no pending Google-created users; Google-created
  users were only ever `pending` if they somehow existed — the refusal branch
  still covers them safely).
