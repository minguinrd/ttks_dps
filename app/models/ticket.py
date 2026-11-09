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


def _display_name(user: User) -> str:
    """Name shown in system comments (same fallback the templates use)."""
    return user.full_name or user.username


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

    def _require_status(self, *allowed: TicketStatus) -> None:
        """Raise ``InvalidTransition`` unless the current status is one of ``allowed``."""
        if self.status not in allowed:
            raise InvalidTransition(
                f"Cannot perform this action while the ticket is {self.status}."
            )

    def claim(self, agent: User) -> None:
        """``open → assigned``: ``agent`` takes the ticket from the queue."""
        self._require_status(TicketStatus.open)
        self.status = TicketStatus.assigned
        self.assignee = agent
        self.add_system_comment(agent, f"Claimed by {_display_name(agent)}.")

    def release(self, actor: User) -> None:
        """``assigned → open``: unclaim the ticket and return it to the queue."""
        self._require_status(TicketStatus.assigned)
        self.status = TicketStatus.open
        self.assignee = None
        self.add_system_comment(actor, f"Released by {_display_name(actor)}.")

    def assign_to(self, agent: User, actor: User) -> None:
        """Set the assignee (``open`` transitions to ``assigned``; reassignment keeps it)."""
        self._require_status(TicketStatus.open, TicketStatus.assigned)
        self.status = TicketStatus.assigned
        self.assignee = agent
        self.add_system_comment(
            actor, f"Assigned to {_display_name(agent)} by {_display_name(actor)}."
        )

    def resolve(self, actor: User, note: str) -> None:
        """``assigned → resolved``: record the resolution note and timestamp."""
        self._require_status(TicketStatus.assigned)
        self.status = TicketStatus.resolved
        self.resolution_note = note
        self.resolved_at = datetime.now(timezone.utc)
        self.add_system_comment(actor, f"Resolved by {_display_name(actor)}.")

    def reopen(self, actor: User) -> None:
        """``resolved → assigned`` or ``closed → assigned`` (admin-only from closed in routes)."""
        self._require_status(TicketStatus.resolved, TicketStatus.closed)
        self.status = TicketStatus.assigned
        self.add_system_comment(actor, f"Reopened by {_display_name(actor)}.")

    def close(self, actor: User) -> None:
        """``open|assigned|resolved → closed``: freeze the ticket and stamp the close time."""
        self._require_status(TicketStatus.open, TicketStatus.assigned, TicketStatus.resolved)
        self.status = TicketStatus.closed
        self.closed_at = datetime.now(timezone.utc)
        self.add_system_comment(actor, f"Closed by {_display_name(actor)}.")
