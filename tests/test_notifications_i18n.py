"""Notification localization: key+params storage and per-reader rendering.

New notifications carry a literal catalog key plus plain params so each
reader's language can render the sentence; legacy rows (``message_key``
``None``) keep rendering the stored ``message`` verbatim.
"""

import json

from app.extensions import db
from app.models import Notification


def test_new_notification_stores_key_and_params(app, client, user_factory, login, ticket_factory):
    requester = user_factory(username="notify-key-owner")
    agent = user_factory(username="notify-key-agent", role="agent")
    outsider = user_factory(username="notify-key-outsider", role="admin")
    ticket = ticket_factory(requester, status="assigned", assignee=agent)
    login(client, outsider)

    resp = client.post(f"/tickets/{ticket.id}/comments", data={"body": "Taking a look."})

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.scalars(
            db.select(Notification).filter_by(ticket_id=ticket.id).order_by(Notification.id)
        ).all()
        assert len(rows) == 2
        for row in rows:
            assert row.message_key == "New comment on ticket #{ticket_id}."
            assert json.loads(row.params) == {"ticket_id": ticket.id}
            # The legacy English sentence is still written, unchanged.
            assert row.message == f"New comment on ticket #{ticket.id}."


def test_notification_renders_in_user_language(app, client, user_factory, login, ticket_factory):
    reader = user_factory(username="notify-i18n-reader", language="es")
    agent = user_factory(username="notify-i18n-agent", role="agent")
    ticket = ticket_factory(reader, status="assigned", assignee=agent)
    login(client, agent)
    client.post(f"/tickets/{ticket.id}/comments", data={"body": "Revisando."})
    client.post("/auth/logout")
    login(client, reader)

    resp = client.get("/notifications")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f"Nuevo comentario en el ticket #{ticket.id}." in html
    assert "New comment on ticket" not in html


def test_legacy_notification_without_key_renders_as_stored(app, client, user_factory, login):
    reader = user_factory(username="notify-legacy-reader")
    with app.app_context():
        db.session.add(
            Notification(
                user_id=reader.id,
                message="New comment on ticket #7.",
                url="/tickets/7",
                message_key=None,
            )
        )
        db.session.commit()
    login(client, reader)

    resp = client.get("/notifications")

    assert resp.status_code == 200
    assert "New comment on ticket #7." in resp.get_data(as_text=True)


def test_notification_params_with_braces_render(app, client, user_factory, login):
    reader = user_factory(username="notify-braces-reader")
    with app.app_context():
        db.session.add(
            Notification(
                user_id=reader.id,
                message="New user {oops} is awaiting approval.",
                url="/admin/",
                message_key="New user {username} is awaiting approval.",
                params=json.dumps({"username": "{oops}"}),
            )
        )
        db.session.commit()
    login(client, reader)

    resp = client.get("/notifications")

    assert resp.status_code == 200
    assert "New user {oops} is awaiting approval." in resp.get_data(as_text=True)
