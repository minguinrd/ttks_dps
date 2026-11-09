import re

from app.extensions import db
from app.models import Comment, Department, Ticket


def test_create_ticket_sets_fields_and_status(app, client, user_factory, login):
    with app.app_context():
        department = Department(name="IT Support")
        db.session.add(department)
        db.session.commit()
        department_id = department.id
    me = user_factory(username="creator", department_id=department_id)
    login(client, me)

    resp = client.post(
        "/tickets/new",
        data={
            "subject": "Printer jams on floor 2",
            "description": "The printer jams on every other page.",
            "category": "hardware",
            "priority": "high",
        },
    )

    assert resp.status_code == 302
    assert re.fullmatch(r"/tickets/\d+", resp.headers["Location"])
    with app.app_context():
        ticket = db.session.scalar(db.select(Ticket))
        assert resp.headers["Location"] == f"/tickets/{ticket.id}"
        assert ticket.status == "open"
        assert ticket.requester_id == me.id
        assert ticket.department_id == department_id


def test_mine_list_shows_only_participants(client, user_factory, login, ticket_factory):
    me = user_factory(username="mina")
    other = user_factory(username="oliver")
    ticket_factory(me, subject="REQUESTED-BY-ME")
    ticket_factory(other, subject="ASSIGNED-TO-ME", assignee=me, status="assigned")
    ticket_factory(other, subject="UNRELATED-TICKET")
    login(client, me)

    resp = client.get("/tickets/mine")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "REQUESTED-BY-ME" in html
    assert "ASSIGNED-TO-ME" in html
    assert "UNRELATED-TICKET" not in html


def test_detail_hidden_from_unrelated_user_404(client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner")
    stranger = user_factory(username="stranger")
    ticket = ticket_factory(owner)
    login(client, stranger)

    resp = client.get(f"/tickets/{ticket.id}")

    assert resp.status_code == 404


def test_agent_sees_any_ticket(client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-view")
    agent = user_factory(username="viewer", role="agent")
    ticket = ticket_factory(owner)
    login(client, agent)

    resp = client.get(f"/tickets/{ticket.id}")

    assert resp.status_code == 200


def test_post_comment(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="commenter")
    ticket = ticket_factory(owner)
    login(client, owner)

    resp = client.post(f"/tickets/{ticket.id}/comments", data={"body": "Any progress on this?"})

    assert resp.status_code == 302
    with app.app_context():
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert len(comments) == 1
        assert comments[0].author_id == owner.id
        assert comments[0].body == "Any progress on this?"
        assert comments[0].is_internal is False


def test_internal_comment_hidden_from_requester(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-note")
    agent = user_factory(username="note-taker", role="agent")
    ticket = ticket_factory(owner)
    login(client, agent)

    resp = client.post(
        f"/tickets/{ticket.id}/comments",
        data={"body": "SECRET-INTERNAL-42", "is_internal": "y"},
    )

    assert resp.status_code == 302
    resp = client.get(f"/tickets/{ticket.id}")
    assert "SECRET-INTERNAL-42" in resp.get_data(as_text=True)

    client.post("/auth/logout")
    login(client, owner)
    resp = client.get(f"/tickets/{ticket.id}")

    assert resp.status_code == 200
    assert "SECRET-INTERNAL-42" not in resp.get_data(as_text=True)


def test_user_cannot_forge_internal_flag(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-forge")
    ticket = ticket_factory(owner)
    login(client, owner)

    resp = client.post(
        f"/tickets/{ticket.id}/comments",
        data={"body": "Trying to sneak a hidden note", "is_internal": "y"},
    )

    assert resp.status_code == 302
    with app.app_context():
        comment = db.session.scalar(db.select(Comment).filter_by(ticket_id=ticket.id))
        assert comment.is_internal is False


def test_agent_internal_note_visible_to_agent(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-peer")
    poster = user_factory(username="poster", role="agent")
    peer = user_factory(username="peer", role="agent")
    ticket = ticket_factory(owner)
    login(client, poster)
    client.post(
        f"/tickets/{ticket.id}/comments",
        data={"body": "INTERNAL-MARKER-77", "is_internal": "y"},
    )

    client.post("/auth/logout")
    login(client, peer)
    resp = client.get(f"/tickets/{ticket.id}")

    assert resp.status_code == 200
    assert "INTERNAL-MARKER-77" in resp.get_data(as_text=True)


def test_cannot_comment_on_closed(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-closed")
    ticket = ticket_factory(owner, status="closed")
    login(client, owner)

    resp = client.post(f"/tickets/{ticket.id}/comments", data={"body": "Late comment"})

    assert resp.status_code == 403
    with app.app_context():
        assert db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all() == []


def test_requester_edits_while_open(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-edit")
    ticket = ticket_factory(owner)
    updated_before = ticket.updated_at
    login(client, owner)

    resp = client.post(
        f"/tickets/{ticket.id}/edit",
        data={
            "subject": "Updated subject",
            "description": "Updated description",
            "category": "software",
            "priority": "urgent",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.subject == "Updated subject"
        assert row.category == "software"
        assert row.priority == "urgent"
        assert row.updated_at > updated_before


def test_requester_cannot_edit_assigned(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-assigned")
    agent = user_factory(username="assignee", role="agent")
    ticket = ticket_factory(
        owner,
        subject="Original subject",
        category="hardware",
        priority="normal",
        status="assigned",
        assignee=agent,
    )
    login(client, owner)

    resp = client.post(
        f"/tickets/{ticket.id}/edit",
        data={
            "subject": "Hijacked subject",
            "description": "Hijacked description",
            "category": "other",
            "priority": "low",
        },
    )

    assert resp.status_code == 403
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.subject == "Original subject"
        assert row.category == "hardware"
        assert row.priority == "normal"


def test_agent_edits_resolved_ticket(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-resolved")
    agent = user_factory(username="fixer", role="agent")
    ticket = ticket_factory(owner, status="resolved", category="hardware")
    login(client, agent)

    resp = client.post(
        f"/tickets/{ticket.id}/edit",
        data={
            "subject": "Recategorized subject",
            "description": "Recategorized description",
            "category": "software",
            "priority": "normal",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.subject == "Recategorized subject"
        assert row.category == "software"
        assert row.status == "resolved"


def test_cannot_edit_closed(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="owner-frozen")
    agent = user_factory(username="closer", role="agent")
    ticket = ticket_factory(owner, status="closed", subject="Frozen subject")
    login(client, owner)

    resp = client.post(
        f"/tickets/{ticket.id}/edit",
        data={
            "subject": "Should not apply",
            "description": "Should not apply",
            "category": "other",
            "priority": "low",
        },
    )
    assert resp.status_code == 403

    client.post("/auth/logout")
    login(client, agent)
    resp = client.post(
        f"/tickets/{ticket.id}/edit",
        data={
            "subject": "Should not apply either",
            "description": "Should not apply either",
            "category": "other",
            "priority": "low",
        },
    )
    assert resp.status_code == 403

    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.subject == "Frozen subject"
