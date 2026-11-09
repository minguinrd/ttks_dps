from app.extensions import db
from app.models import Notification


def test_claim_notifies_assignee(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="notify-claim-owner")
    agent = user_factory(username="notify-claim-agent", role="agent")
    ticket = ticket_factory(owner)
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/claim")

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket.id).order_by(Notification.id)
        ).all()
        assert [row.user_id for row in rows] == [agent.id]
        assert rows[0].message == f"Ticket #{ticket.id} has been assigned to you."
        assert rows[0].url == f"/tickets/{ticket.id}"
        assert rows[0].is_read is False

    # Assigning notifies the new assignee the same way.
    admin = user_factory(username="notify-assign-admin", role="admin")
    second = user_factory(username="notify-assign-agent", role="agent")
    ticket2 = ticket_factory(owner)
    client.post("/auth/logout")
    login(client, admin)

    resp = client.post(f"/tickets/{ticket2.id}/assign", data={"agent_id": second.id})

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket2.id).order_by(Notification.id)
        ).all()
        assert [row.user_id for row in rows] == [second.id]
        assert rows[0].message == f"Ticket #{ticket2.id} has been assigned to you."


def test_public_comment_notifies_requester_and_assignee_not_actor(
    app, client, user_factory, login, ticket_factory
):
    requester = user_factory(username="notify-cmt-owner")
    agent = user_factory(username="notify-cmt-agent", role="agent")
    outsider = user_factory(username="notify-cmt-admin", role="admin")
    ticket = ticket_factory(requester, status="assigned", assignee=agent)
    other_ticket = ticket_factory(requester, status="assigned", assignee=agent)

    # A comment from someone who is neither requester nor assignee notifies both.
    login(client, outsider)

    resp = client.post(f"/tickets/{ticket.id}/comments", data={"body": "Taking a look."})

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(db.select(Notification).filter_by(ticket_id=ticket.id)).all()
        assert {row.user_id for row in rows} == {requester.id, agent.id}
        assert all(row.message == f"New comment on ticket #{ticket.id}." for row in rows)
        assert all(row.url == f"/tickets/{ticket.id}" for row in rows)

    # A comment from the assignee notifies only the requester (the actor is excluded).
    client.post("/auth/logout")
    login(client, agent)

    resp = client.post(f"/tickets/{other_ticket.id}/comments", data={"body": "Working on it."})

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=other_ticket.id).order_by(Notification.id)
        ).all()
        assert [row.user_id for row in rows] == [requester.id]

    # A repeated identical comment does not spam an unread duplicate.
    resp = client.post(f"/tickets/{other_ticket.id}/comments", data={"body": "Working on it."})

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=other_ticket.id).order_by(Notification.id)
        ).all()
        assert [row.user_id for row in rows] == [requester.id]


def test_internal_comment_creates_no_requester_notification(
    app, client, user_factory, login, ticket_factory
):
    requester = user_factory(username="notify-int-owner")
    agent = user_factory(username="notify-int-agent", role="agent")
    ticket = ticket_factory(requester, status="assigned", assignee=agent)
    login(client, agent)

    # A public comment produces the notification; the internal one must add none.
    resp = client.post(f"/tickets/{ticket.id}/comments", data={"body": "Open question."})
    assert resp.status_code == 302

    resp = client.post(
        f"/tickets/{ticket.id}/comments", data={"body": "Hidden note.", "is_internal": "y"}
    )

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket.id).order_by(Notification.id)
        ).all()
        assert [row.user_id for row in rows] == [requester.id]
        assert rows[0].message == f"New comment on ticket #{ticket.id}."


def test_status_change_notifies_requester(app, client, user_factory, login, ticket_factory):
    requester = user_factory(username="notify-st-owner")
    agent = user_factory(username="notify-st-agent", role="agent")
    ticket = ticket_factory(requester, status="assigned", assignee=agent)
    login(client, agent)

    # resolve, reopen (by an agent) and close all notify the requester.
    resp = client.post(
        f"/tickets/{ticket.id}/resolve", data={"resolution_note": "Replaced the cable."}
    )
    assert resp.status_code == 302
    resp = client.post(f"/tickets/{ticket.id}/reopen")
    assert resp.status_code == 302
    resp = client.post(f"/tickets/{ticket.id}/close")
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket.id).order_by(Notification.id)
        ).all()
        assert {row.user_id for row in rows} == {requester.id}
        assert [row.message for row in rows] == [
            f"Ticket #{ticket.id} has been resolved.",
            f"Ticket #{ticket.id} has been reopened.",
            f"Ticket #{ticket.id} has been closed.",
        ]

    # A reopen by the requester notifies the assignee instead.
    owner_two = user_factory(username="notify-st-owner2")
    agent_two = user_factory(username="notify-st-agent2", role="agent")
    ticket_two = ticket_factory(owner_two, status="resolved", assignee=agent_two)
    client.post("/auth/logout")
    login(client, owner_two)

    resp = client.post(f"/tickets/{ticket_two.id}/reopen")

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(db.select(Notification).filter_by(ticket_id=ticket_two.id)).all()
        assert [row.user_id for row in rows] == [agent_two.id]
        assert rows[0].message == f"Ticket #{ticket_two.id} has been reopened."

    # A reopen by an admin notifies the requester, not the agent holding the ticket.
    owner_three = user_factory(username="notify-st-owner3")
    agent_three = user_factory(username="notify-st-agent3", role="agent")
    admin = user_factory(username="notify-st-admin", role="admin")
    ticket_three = ticket_factory(owner_three, status="closed", assignee=agent_three)
    client.post("/auth/logout")
    login(client, admin)

    resp = client.post(f"/tickets/{ticket_three.id}/reopen")

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket_three.id)
        ).all()
        assert [row.user_id for row in rows] == [owner_three.id]


def test_new_pending_registration_notifies_admins(app, client, user_factory):
    admin_one = user_factory(username="notify-admin-one", role="admin")
    admin_two = user_factory(username="notify-admin-two", role="admin")
    user_factory(username="notify-admin-agent", role="agent")

    resp = client.post(
        "/auth/register",
        data={
            "username": "newbie",
            "password": "pass12345",
            "confirm": "pass12345",
            "full_name": "New Bee",
            "email": "newbie@example.com",
            "department": "",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(db.select(Notification).order_by(Notification.id)).all()
        assert {row.user_id for row in rows} == {admin_one.id, admin_two.id}
        assert all(row.message == "New user newbie is awaiting approval." for row in rows)
        assert all(row.url == "/admin/" for row in rows)
        assert all(row.ticket_id is None for row in rows)


def test_unread_count_and_read_endpoints(app, client, user_factory, login):
    user = user_factory(username="notify-count-user")
    other = user_factory(username="notify-count-other")
    with app.app_context():
        own_rows = []
        for i in range(3):
            row = Notification(user_id=user.id, message=f"Update {i}", url=f"/tickets/{i}")
            db.session.add(row)
            own_rows.append(row)
        db.session.add(Notification(user_id=other.id, message="Other update", url="/tickets/99"))
        db.session.commit()
        first_id = own_rows[0].id

    from app.notifications import unread_count

    login(client, user)

    resp = client.get("/notifications")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'href="/notifications"' in html
    assert 'id="unread-badge">3</span>' in html
    assert "Update 0" in html
    assert "Other update" not in html  # own list only
    with app.app_context():
        assert unread_count(user) == 3

    resp = client.post(f"/notifications/{first_id}/read")

    assert resp.status_code == 302
    with app.app_context():
        assert unread_count(user) == 2
    resp = client.get("/notifications")
    assert 'id="unread-badge">2</span>' in resp.get_data(as_text=True)

    resp = client.post("/notifications/read-all")

    assert resp.status_code == 302
    with app.app_context():
        assert unread_count(user) == 0
        assert unread_count(other) == 1  # read-all never touches other users
    resp = client.get("/notifications")
    assert "unread-badge" not in resp.get_data(as_text=True)


def test_cannot_read_others_notifications(app, client, user_factory, login):
    agent = user_factory(username="notify-guard-agent", role="agent")
    other = user_factory(username="notify-guard-other")
    with app.app_context():
        notification = Notification(user_id=agent.id, message="Ping.", url="/tickets/1")
        db.session.add(notification)
        db.session.commit()
        notification_id = notification.id

    login(client, other)

    resp = client.post(f"/notifications/{notification_id}/read")

    assert resp.status_code == 404
    with app.app_context():
        assert db.session.get(Notification, notification_id).is_read is False

    # read-all does not reach into other users' rows either
    resp = client.post("/notifications/read-all")
    with app.app_context():
        assert db.session.get(Notification, notification_id).is_read is False

    # the owner can still mark it read
    client.post("/auth/logout")
    login(client, agent)

    resp = client.post(f"/notifications/{notification_id}/read")

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Notification, notification_id).is_read is True
