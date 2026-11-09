import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Category,
    Comment,
    Department,
    Notification,
    Priority,
    Ticket,
    TicketStatus,
    User,
)


@pytest.fixture()
def session(app):
    """Create the schema in the test database and yield a ready db.session."""
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.session.remove()
        db.drop_all()


def test_user_password_roundtrip(session):
    user = User(username="alice")
    user.set_password("s3cret!")
    session.add(user)
    session.commit()
    user_id = user.id

    session.expire_all()
    loaded = session.get(User, user_id)
    assert loaded.check_password("s3cret!") is True
    assert loaded.check_password("wrong") is False


def test_user_is_active_property(session):
    users = {
        "active": User(username="active", status="active"),
        "pending": User(username="pending", status="pending"),
        "default": User(username="default"),
        "suspended": User(username="suspended", status="suspended"),
    }
    for user in users.values():
        user.set_password("pw")
    session.add_all(users.values())
    session.commit()
    session.expire_all()

    assert users["active"].is_active is True
    assert users["default"].status == "pending"
    assert users["pending"].is_active is False
    assert users["default"].is_active is False
    assert users["suspended"].is_active is False


def test_username_unique(session):
    first = User(username="dup")
    first.set_password("pw")
    second = User(username="dup")
    second.set_password("pw")
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_department_name_unique(session):
    session.add_all([Department(name="Ops"), Department(name="Ops")])

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_ticket_defaults(session):
    requester = User(username="alice")
    requester.set_password("pw")
    ticket = Ticket(
        subject="Screen flicker",
        description="External monitor flickers.",
        category=Category.hardware,
        priority=Priority.low,
        requester=requester,
    )
    session.add(ticket)
    session.commit()

    assert ticket.status == "open"
    assert ticket.status == TicketStatus.open
    assert ticket.id is not None
    assert ticket.assignee_id is None
    assert ticket.resolved_at is None
    assert ticket.closed_at is None


def test_comment_and_notification_roundtrip(session):
    requester = User(username="alice")
    requester.set_password("pw")
    ticket = Ticket(
        subject="VPN down",
        description="Cannot reach the VPN gateway.",
        category=Category.network,
        priority=Priority.urgent,
        requester=requester,
    )
    session.add(ticket)
    comment = ticket.add_system_comment(requester, "Investigating.")
    notification = Notification(
        user=requester,
        ticket=ticket,
        message="Your ticket was updated.",
        url="/tickets/1",
    )
    session.add(notification)
    session.commit()
    ticket_id, comment_id, notification_id = ticket.id, comment.id, notification.id

    session.expire_all()
    loaded_ticket = session.get(Ticket, ticket_id)
    assert loaded_ticket.requester.username == "alice"
    assert [c.body for c in loaded_ticket.comments] == ["Investigating."]

    loaded_comment = session.get(Comment, comment_id)
    assert loaded_comment.ticket_id == ticket_id
    assert loaded_comment.author.username == "alice"
    assert loaded_comment.is_internal is False

    loaded_notification = session.get(Notification, notification_id)
    assert loaded_notification.ticket_id == ticket_id
    assert loaded_notification.user_id == requester.id
    assert loaded_notification.is_read is False
