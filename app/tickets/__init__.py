from flask import Blueprint

tickets_bp = Blueprint("tickets", __name__, url_prefix="/tickets")

from app.tickets import routes  # noqa: E402, F401  # register routes on the blueprint
