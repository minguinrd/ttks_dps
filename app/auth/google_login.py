"""Google sign-in account matching: find or create a user for a Google identity."""

import secrets

from app.extensions import db
from app.models import User


class GoogleAuthError(Exception):
    """A Google identity cannot be safely mapped to an account (sub/email conflict)."""


def find_or_create_google_user(email: str, *, sub: str, name: str | None) -> tuple[User, bool]:
    """Match a Google identity to a user, creating a pending user when new.

    Returns ``(user, created)``. The Google ``sub`` is the primary key of the
    identity: it wins over an email match. An email match that carries a
    *different* ``google_sub`` is an identity conflict and raises
    :class:`GoogleAuthError`. A link-less email match gets its ``google_sub``
    set. New users land as ``pending`` so the admin approval flow still gates
    every first sign-in. Commits the session.
    """
    user = db.session.scalar(db.select(User).filter_by(google_sub=sub))
    if user is not None:
        return user, False

    lowered = email.lower()
    user = db.session.scalar(db.select(User).filter(db.func.lower(User.email) == lowered))
    if user is not None:
        if user.google_sub is not None:
            raise GoogleAuthError("email already linked to a different Google account")
        user.google_sub = sub
        db.session.commit()
        return user, False

    base = lowered.split("@", 1)[0]
    username, suffix = base, 1
    while db.session.scalar(db.select(User.id).filter_by(username=username)) is not None:
        suffix += 1
        username = f"{base}-{suffix}"

    user = User(
        username=username,
        full_name=name,
        email=lowered,
        status="pending",
        role="user",
        department_id=None,
        google_sub=sub,
    )
    # A random password keeps password login impossible for auto-created
    # accounts until an admin sets one.
    user.set_password(secrets.token_urlsafe(32))
    db.session.add(user)
    db.session.commit()
    return user, True
