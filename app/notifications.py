import json

from app.extensions import db
from app.models import Notification, User


def notify(
    user_ids: list[int],
    message: str,
    url: str,
    *,
    ticket_id: int | None = None,
    key: str | None = None,
    params: dict | None = None,
) -> None:
    """Create one unread notification row per recipient.

    ``message`` is the legacy English sentence, written unchanged;
    ``key`` is a literal ``app.i18n`` catalog key and ``params`` its dict of
    plain values, persisted alongside so each reader renders the sentence in
    their own language. Recipients who already hold an identical unread row
    (same ``message`` and ``url``) are skipped, so repeated events do not spam
    the same ping. The caller commits the session.
    """
    recipients = set(user_ids)
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
                ticket_id=ticket_id,
                message=message,
                url=url,
                message_key=key,
                params=json.dumps(params) if params is not None else None,
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
