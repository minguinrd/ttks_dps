from app.extensions import db
from app.models import Notification, Ticket, User


def notify(
    recipient_ids: list[int],
    message: str,
    url: str,
    ticket: Ticket | None = None,
    exclude_id: int | None = None,
) -> None:
    """Create one unread notification row per recipient.

    Skips ``exclude_id`` (typically the actor) and recipients who already hold
    an identical unread row (same ``message`` and ``url``), so repeated events
    do not spam the same ping. The caller commits the session.
    """
    recipients = {user_id for user_id in recipient_ids if user_id != exclude_id}
    if not recipients:
        return
    already_notified = set(
        db.session.scalars(
            db.select(Notification.user_id).where(
                Notification.user_id.in_(recipients),
                Notification.message == message,
                Notification.url == url,
                Notification.is_read.is_(False),
            )
        ).all()
    )
    for user_id in recipients - already_notified:
        db.session.add(
            Notification(
                user_id=user_id,
                ticket_id=ticket.id if ticket is not None else None,
                message=message,
                url=url,
            )
        )


def unread_count(user: User) -> int:
    """Number of unread notifications belonging to ``user``."""
    return db.session.scalar(
        db.select(db.func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
