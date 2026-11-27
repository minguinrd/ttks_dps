"""New-ticket page: priority default and choices, duplicates nudge, errors."""

import re
from pathlib import Path

from app.extensions import db
from app.models import Department, Ticket

_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "app.js"


def test_priority_defaults_to_normal_with_descriptions(client, user_factory, login):
    login(client, user_factory(username="nt-default"))

    html = client.get("/tickets/new").get_data(as_text=True)

    checked = re.findall(r'name="priority"\s+value="(\w+)"\s+checked', html)
    assert checked == ["normal"]
    assert html.count('type="radio"') == 4
    assert "It stops me from doing my work." in html


def test_radio_priority_posts_like_the_select(app, client, user_factory, login, category_ids):
    me = user_factory(username="nt-post")
    login(client, me)

    resp = client.post(
        "/tickets/new",
        data={
            "subject": "VPN drops",
            "description": "Every ten minutes.",
            "category_id": str(category_ids["Network"]),
            "priority": "urgent",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(Ticket.priority)) == "urgent"


def test_invalid_submit_keeps_choice_and_marks_errors(client, user_factory, login, category_ids):
    login(client, user_factory(username="nt-invalid"))

    html = client.post(
        "/tickets/new",
        data={
            "subject": "",
            "description": "x",
            "category_id": str(category_ids["Other"]),
            "priority": "high",
        },
    ).get_data(as_text=True)

    assert re.search(r'name="priority"\s+value="high"\s+checked', html)
    assert 'aria-invalid="true"' in html
    # No autofocus on re-render: the script focuses the first invalid field.
    assert "autofocus" not in html


def test_pending_tickets_listed_to_avoid_duplicates(client, user_factory, login, ticket_factory):
    me = user_factory(username="nt-dupes")
    ticket_factory(me, subject="PRINTER-STILL-BROKEN", status="assigned")
    ticket_factory(me, subject="OLD-AND-CLOSED", status="closed")
    login(client, me)

    html = client.get("/tickets/new").get_data(as_text=True)

    assert "Already reported?" in html
    assert "PRINTER-STILL-BROKEN" in html
    assert "OLD-AND-CLOSED" not in html


def test_department_is_shown(app, client, user_factory, login):
    with app.app_context():
        department = Department(name="Finance")
        db.session.add(department)
        db.session.commit()
        department_id = department.id
    login(client, user_factory(username="nt-dept", department_id=department_id))

    assert "Filed under your department: Finance." in client.get("/tickets/new").get_data(
        as_text=True
    )


def test_form_opts_into_draft_saving():
    js = _JS.read_text(encoding="utf-8")

    assert "form[data-draft]" in js
    assert "sessionStorage" in js
    assert "beforeunload" in js
