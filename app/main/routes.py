from flask import redirect
from flask_login import current_user, login_required

from app.main import main_bp
from app.models import Role


@main_bp.route("/")
@login_required
def index():
    # Hardcoded paths on purpose: the tickets routes land in a later task and
    # these exact paths are pinned by the spec, so no url_for here.
    if current_user.role == Role.user:
        return redirect("/tickets/mine")
    return redirect("/tickets/queue")
