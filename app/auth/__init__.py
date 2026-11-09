from flask import Blueprint

from app.extensions import db, login_manager
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        return db.session.get(User, int(user_id))
    except ValueError:
        return None


from app.auth import routes  # noqa: E402, F401  # register routes on the blueprint
