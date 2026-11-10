from flask import Blueprint

from app.extensions import db, login_manager
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        user = db.session.get(User, int(user_id))
    except ValueError:
        return None
    # Suspended accounts must lose their existing session, not just be unable
    # to log in: returning None makes Flask-Login treat the request as anonymous.
    if user is None or not user.is_active:
        return None
    return user


from app.auth import routes  # noqa: E402, F401  # register routes on the blueprint
