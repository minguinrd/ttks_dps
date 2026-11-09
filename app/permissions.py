from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles: str):
    """Wrap a view so it aborts with 403 unless the current user's role is one of ``roles``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
