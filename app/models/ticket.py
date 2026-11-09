from datetime import datetime, timezone
from enum import StrEnum

from app.extensions import db
from app.models.user import User


class TicketStatus(StrEnum):
    open = "open"
    assigned = "assigned"
    resolved = "resolved"
    closed = "closed"


class Category(StrEnum):
    hardware = "hardware"
    software = "software"
    network = "network"
    access = "access"
    other = "other"


class Priority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class InvalidTransition(Exception):
    """Raised when a ticket status transition is not allowed."""


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    ticket = db.relationship("Ticket", back_populates="comments")
    author = db.relationship("User")


class Ticket(db.Model):
    __tablename__ = "tickets"

    # id doubles as the sequential display number (shown as #<id>).
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    resolution_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    resolved_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    requester = db.relationship("User", foreign_keys=[requester_id])
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    department = db.relationship("Department")
    comments = db.relationship("Comment", back_populates="ticket", order_by="Comment.created_at")

    def add_system_comment(self, actor: User, text: str) -> Comment:
        comment = Comment(ticket=self, author=actor, body=text)
        db.session.add(comment)
        return comment
