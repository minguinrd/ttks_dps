from app.extensions import db
from app.models import Comment, Ticket

INVALID_TRANSITION_MESSAGE = "This action is not allowed for the current ticket status."


def test_claim_open_ticket(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="claim-owner")
    agent = user_factory(username="claim-agent", role="agent", full_name="Alice Agent")
    ticket = ticket_factory(owner)
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/claim")

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        assert row.assignee_id == agent.id
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Claimed by Alice Agent."]
        assert comments[0].is_internal is False


def test_release_returns_to_open(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="release-owner")
    agent = user_factory(username="release-agent", role="agent", full_name="Bob Agent")
    ticket = ticket_factory(owner, status="assigned", assignee=agent)
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/release")

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "open"
        assert row.assignee_id is None
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Released by Bob Agent."]


def test_admin_assigns_to_agent(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="assign-owner")
    agent = user_factory(username="assign-target", role="agent", full_name="Cara Agent")
    admin = user_factory(username="assign-admin", role="admin", full_name="Dan Admin")
    ticket = ticket_factory(owner)
    login(client, admin)

    resp = client.post(f"/tickets/{ticket.id}/assign", data={"agent_id": agent.id})

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        assert row.assignee_id == agent.id
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Assigned to Cara Agent by Dan Admin."]


def test_resolve_requires_note(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="note-owner")
    agent = user_factory(username="note-agent", role="agent")
    ticket = ticket_factory(owner, status="assigned", assignee=agent)
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/resolve", data={"resolution_note": ""})

    assert resp.status_code == 200
    assert "This field is required." in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        assert row.resolution_note is None


def test_resolve_sets_note_and_resolved_at(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="resolve-owner")
    agent = user_factory(username="resolve-agent", role="agent", full_name="Eve Agent")
    ticket = ticket_factory(owner, status="assigned", assignee=agent)
    login(client, agent)

    resp = client.post(
        f"/tickets/{ticket.id}/resolve", data={"resolution_note": "Replaced the cable."}
    )

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "resolved"
        assert row.resolution_note == "Replaced the cable."
        assert row.resolved_at is not None
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Resolved by Eve Agent."]


def test_reopen_from_resolved_with_comment(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="reopen-owner", full_name="Fay Owner")
    agent = user_factory(username="reopen-agent", role="agent")
    ticket = ticket_factory(owner, status="resolved", assignee=agent)
    login(client, owner)

    resp = client.post(
        f"/tickets/{ticket.id}/reopen", data={"comment": "Still broken after the fix."}
    )

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        comments = db.session.scalars(
            db.select(Comment).filter_by(ticket_id=ticket.id).order_by(Comment.id)
        ).all()
        assert [comment.body for comment in comments] == [
            "Reopened by Fay Owner.",
            "Still broken after the fix.",
        ]
        assert comments[1].is_internal is False


def test_close_from_open_by_requester(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="close-owner", full_name="Gil Owner")
    ticket = ticket_factory(owner)
    login(client, owner)

    resp = client.post(f"/tickets/{ticket.id}/close")

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "closed"
        assert row.closed_at is not None
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Closed by Gil Owner."]


def test_close_from_resolved_allowed(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="close-res-owner")
    agent = user_factory(username="close-res-agent", role="agent")
    ticket = ticket_factory(owner, status="resolved", assignee=agent)
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/close")

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "closed"
        assert row.closed_at is not None


def test_claim_already_assigned_rejected(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="double-claim-owner")
    first = user_factory(username="first-agent", role="agent")
    second = user_factory(username="second-agent", role="agent")
    ticket = ticket_factory(owner, status="assigned", assignee=first)
    login(client, second)

    resp = client.post(f"/tickets/{ticket.id}/claim", follow_redirects=True)

    assert resp.status_code == 200
    assert INVALID_TRANSITION_MESSAGE in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        assert row.assignee_id == first.id
        assert db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all() == []


def test_user_cannot_claim_403(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="plain-claimer")
    ticket = ticket_factory(owner)
    login(client, owner)

    resp = client.post(f"/tickets/{ticket.id}/claim")

    assert resp.status_code == 403
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "open"
        assert row.assignee_id is None


def test_non_assignee_agent_cannot_resolve_403(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="resolve-guard-owner")
    assignee = user_factory(username="real-assignee", role="agent")
    other = user_factory(username="other-agent", role="agent")
    ticket = ticket_factory(owner, status="assigned", assignee=assignee)
    login(client, other)

    resp = client.post(
        f"/tickets/{ticket.id}/resolve", data={"resolution_note": "Not mine to resolve."}
    )

    assert resp.status_code == 403
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        assert row.resolution_note is None


def test_reopen_closed_admin_only(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="reopen-closed-owner")
    agent = user_factory(username="reopen-closed-agent", role="agent")
    ticket = ticket_factory(owner, status="closed")
    login(client, agent)

    resp = client.post(f"/tickets/{ticket.id}/reopen")

    assert resp.status_code == 403
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "closed"

    client.post("/auth/logout")
    admin = user_factory(username="reopen-closed-admin", role="admin", full_name="Hal Admin")
    login(client, admin)

    resp = client.post(f"/tickets/{ticket.id}/reopen")

    assert resp.status_code == 302
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "assigned"
        comments = db.session.scalars(db.select(Comment).filter_by(ticket_id=ticket.id)).all()
        assert [comment.body for comment in comments] == ["Reopened by Hal Admin."]


def test_resolve_unassigned_open_rejected(app, client, user_factory, login, ticket_factory):
    owner = user_factory(username="open-resolve-owner")
    admin = user_factory(username="open-resolve-admin", role="admin")
    ticket = ticket_factory(owner)
    login(client, admin)

    resp = client.post(
        f"/tickets/{ticket.id}/resolve",
        data={"resolution_note": "Should not stick."},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert INVALID_TRANSITION_MESSAGE in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.get(Ticket, ticket.id)
        assert row.status == "open"
        assert row.resolution_note is None
