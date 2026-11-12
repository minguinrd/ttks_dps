import json
from datetime import datetime, timezone

from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"))
    message = db.Column(db.Text, nullable=False)
    message_key = db.Column(db.Text)
    params = db.Column(db.Text)
    url = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User")
    ticket = db.relationship("Ticket")

    @property
    def parsed_params(self) -> dict:
        """``params`` JSON decoded for rendering (``{}`` when unset or corrupt).

        A single bad row must never crash the notifications page.
        """
        try:
            params = json.loads(self.params) if self.params else {}
        except ValueError:  # includes json.JSONDecodeError
            return {}
        return params if isinstance(params, dict) else {}
