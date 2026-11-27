"""Ticket page: translated status events, read-on-view, context panels."""

import re
from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models import Comment, Notification, Ticket


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_status_changes_render_as_translated_events(
    app, client, user_factory, login, ticket_factory
):
    owner = user_factory(username="det-owner", language="es")
    agent = user_factory(username="det-agent", role="agent", full_name="Ana Ruiz")
    ticket = ticket_factory(owner)
    login(client, agent)
    client.post(f"/tickets/{ticket.id}/claim")
    client.post(f"/tickets/{ticket.id}/comments", data={"body": "Looking into it."})

    with app.app_context():
        stored = db.session.scalars(
            db.select(Comment).where(Comment.ticket_id == ticket.id).order_by(Comment.id)
        ).all()
        # Stored in English; only the event is flagged as a system entry.
        assert [(c.body, c.is_system) for c in stored] == [
            ("Claimed by Ana Ruiz.", True),
            ("Looking into it.", False),
        ]

    client.post("/auth/logout")
    login(client, owner)
    html = client.get(f"/tickets/{ticket.id}").get_data(as_text=True)

    assert 'class="thread-event"' in html
    assert "Ana Ruiz tomó el ticket." in _text(html)
    assert "Claimed by" not in html
    # The count in the heading is people's comments only.
    assert "Hilo (1)" in _text(html)


def test_opening_a_ticket_marks_its_notifications_read(
    app, client, user_factory, login, ticket_factory
):
    owner = user_factory(username="det-read-owner")
    ticket = ticket_factory(owner)
    other = ticket_factory(owner)
    with app.app_context():
        for target in (ticket, other):
            db.session.add(
                Notification(
                    user_id=owner.id, ticket_id=target.id, message="x", url="/", is_read=False
                )
            )
        db.session.commit()
    login(client, owner)

    client.get(f"/tickets/{ticket.id}")

    with app.app_context():
        unread = db.session.scalars(
            db.select(Notification.ticket_id).where(
                Notification.user_id == owner.id, Notification.is_read.is_(False)
            )
        ).all()
    assert unread == [other.id]


def test_reopen_confirmation_matches_destination(client, user_factory, login, ticket_factory):
    owner = user_factory(username="det-reopen-owner")
    agent = user_factory(username="det-reopen-agent", role="agent")
    queued = ticket_factory(owner, status="resolved")
    held = ticket_factory(owner, status="resolved", assignee=agent)
    login(client, owner)

    assert "It goes back to the queue." in client.get(f"/tickets/{queued.id}").get_data(
        as_text=True
    )
    assert "It goes back to the assigned state." in client.get(f"/tickets/{held.id}").get_data(
        as_text=True
    )


def test_resolved_ticket_shows_time_to_resolve(client, user_factory, login, ticket_factory):
    owner = user_factory(username="det-time-owner")
    agent = user_factory(username="det-time-agent", role="agent")
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    ticket = ticket_factory(
        owner,
        status="resolved",
        assignee=agent,
        created_at=now - timedelta(hours=6),
        resolved_at=now - timedelta(hours=1),
    )
    login(client, owner)

    assert "Time to resolve 5 h" in _text(
        client.get(f"/tickets/{ticket.id}").get_data(as_text=True)
    )


def test_staff_see_requesters_other_tickets(client, user_factory, login, ticket_factory):
    owner = user_factory(username="det-rel-owner", full_name="Rita Req")
    agent = user_factory(username="det-rel-agent", role="agent")
    current = ticket_factory(owner, subject="CURRENT-ONE")
    ticket_factory(owner, subject="EARLIER-PROBLEM")

    login(client, agent)
    html = client.get(f"/tickets/{current.id}").get_data(as_text=True)
    assert "More from Rita Req" in html
    assert "EARLIER-PROBLEM" in html

    # Requesters never get the panel (it would only list their own tickets).
    client.post("/auth/logout")
    login(client, owner)
    assert "More from" not in client.get(f"/tickets/{current.id}").get_data(as_text=True)


def test_internal_composer_explains_visibility(client, user_factory, login, ticket_factory):
    owner = user_factory(username="det-comp-owner")
    agent = user_factory(username="det-comp-agent", role="agent")
    ticket = ticket_factory(owner)

    login(client, agent)
    assert "Only agents and admins will see this note." in client.get(
        f"/tickets/{ticket.id}"
    ).get_data(as_text=True)

    client.post("/auth/logout")
    login(client, owner)
    assert "Only agents and admins will see this note." not in client.get(
        f"/tickets/{ticket.id}"
    ).get_data(as_text=True)


def test_system_flag_defaults_false_for_people(app, user_factory, ticket_factory):
    owner = user_factory(username="det-flag-owner")
    ticket = ticket_factory(owner)
    with app.app_context():
        db.session.add(Comment(ticket_id=ticket.id, author_id=owner.id, body="Closed by mistake."))
        db.session.commit()
        comment = db.session.scalar(db.select(Comment).where(Comment.ticket_id == ticket.id))
        assert comment.is_system is False
        assert db.session.get(Ticket, ticket.id) is not None
