import re

import pytest

from app.extensions import db
from app.models import Department


def _row_ids(html: str) -> set[int]:
    """Ticket numbers rendered as ``>#<id></a>`` links in the queue rows."""
    return {int(number) for number in re.findall(r">#(\d+)</a>", html)}


def test_queue_requires_agent_role(client, user_factory, login):
    plain = user_factory(username="queue-user")
    agent = user_factory(username="queue-agent", role="agent")

    resp = client.get("/tickets/queue")

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login")

    login(client, plain)
    resp = client.get("/tickets/queue")

    assert resp.status_code == 403

    client.post("/auth/logout")
    login(client, agent)
    resp = client.get("/tickets/queue")

    assert resp.status_code == 200


def test_queue_lists_all_tickets(client, user_factory, login, ticket_factory):
    owner = user_factory(username="queue-owner")
    agent = user_factory(username="queue-viewer", role="agent")
    tickets = [ticket_factory(owner, subject=f"Queue ticket {n}") for n in range(3)]
    login(client, agent)

    resp = client.get("/tickets/queue")

    assert resp.status_code == 200
    assert _row_ids(resp.get_data(as_text=True)) == {ticket.id for ticket in tickets}


# Each case filters on one query param; the filter value is the named ticket's own
# field for that param (e.g. alpha.status == "open") and the expected rows are named.
FILTER_CASES = [
    ("status", "alpha", {"alpha", "beta"}),
    ("category", "alpha", {"alpha", "gamma"}),
    ("priority", "beta", {"beta", "gamma"}),
    ("department_id", "alpha", {"alpha", "gamma"}),
    ("requester_id", "beta", {"beta", "gamma"}),
]


@pytest.mark.parametrize(("param", "value_source", "expected"), FILTER_CASES)
def test_queue_filters(
    app, client, user_factory, login, ticket_factory, param, value_source, expected
):
    with app.app_context():
        it = Department(name="IT")
        hr = Department(name="HR")
        db.session.add_all([it, hr])
        db.session.commit()
        it_id, hr_id = it.id, hr.id
    alice = user_factory(username="req-alice", department_id=it_id)
    bob = user_factory(username="req-bob", department_id=hr_id)
    agent = user_factory(username="queue-agent", role="agent")
    named = {
        "alpha": ticket_factory(
            alice,
            subject="Alpha",
            status="open",
            category="hardware",
            priority="high",
            department_id=it_id,
        ),
        "beta": ticket_factory(
            bob,
            subject="Beta",
            status="open",
            category="software",
            priority="low",
            department_id=hr_id,
        ),
        "gamma": ticket_factory(
            bob,
            subject="Gamma",
            status="assigned",
            category="hardware",
            priority="low",
            department_id=it_id,
            assignee=agent,
        ),
    }
    login(client, agent)

    resp = client.get(f"/tickets/queue?{param}={getattr(named[value_source], param)}")

    assert resp.status_code == 200
    assert _row_ids(resp.get_data(as_text=True)) == {named[name].id for name in expected}


def test_queue_claim_button_only_for_open_tickets(client, user_factory, login, ticket_factory):
    owner = user_factory(username="claim-row-owner")
    agent = user_factory(username="claim-row-agent", role="agent")
    open_ticket = ticket_factory(owner, subject="OPEN-FOR-CLAIM")
    taken = ticket_factory(owner, subject="ALREADY-TAKEN", status="assigned", assignee=agent)
    login(client, agent)

    resp = client.get("/tickets/queue")

    html = resp.get_data(as_text=True)
    assert ">Claim</button>" in html
    assert f"/tickets/{open_ticket.id}/claim" in html
    assert f"/tickets/{taken.id}/claim" not in html
