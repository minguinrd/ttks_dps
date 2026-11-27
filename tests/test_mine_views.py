"""My Tickets: tabs, scope, search, update marks and the resolved callout."""

import re

from app.extensions import db
from app.models import Notification
from app.tickets.routes import MINE_PER_PAGE


def _row_ids(html):
    return [int(n) for n in re.findall(r">#(\d+)</a>", html)]


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_default_tab_is_pending_and_tabs_count(client, user_factory, login, ticket_factory):
    me = user_factory(username="mv-me")
    active = ticket_factory(me, status="open")
    done = ticket_factory(me, status="resolved")
    shut = ticket_factory(me, status="closed")
    login(client, me)

    html = client.get("/tickets/mine").get_data(as_text=True)
    assert _row_ids(html) == [active.id]
    text = _text(html)
    assert "Pending 1" in text and "Resolved 1" in text and "Closed 1" in text and "All 3" in text

    assert _row_ids(client.get("/tickets/mine?status=closed").get_data(as_text=True)) == [shut.id]
    assert set(_row_ids(client.get("/tickets/mine?status=all").get_data(as_text=True))) == {
        active.id,
        done.id,
        shut.id,
    }


def test_resolved_tickets_prompt_the_requester(client, user_factory, login, ticket_factory):
    me = user_factory(username="mv-prompt")
    ticket_factory(me, status="resolved")
    login(client, me)

    text = _text(client.get("/tickets/mine").get_data(as_text=True))
    assert "One of your tickets has been resolved." in text
    # The callout is redundant on the Resolved tab itself.
    text = _text(client.get("/tickets/mine?status=resolved").get_data(as_text=True))
    assert "has been resolved." not in text


def test_staff_scope_splits_opened_and_assigned(client, user_factory, login, ticket_factory):
    agent = user_factory(username="mv-agent", role="agent")
    other = user_factory(username="mv-other")
    opened = ticket_factory(agent, subject="OPENED-BY-AGENT")
    held = ticket_factory(other, status="assigned", assignee=agent)
    login(client, agent)

    def ids(query):
        return set(_row_ids(client.get(f"/tickets/mine?{query}").get_data(as_text=True)))

    assert ids("") == {opened.id, held.id}
    assert ids("scope=requested") == {opened.id}
    assert ids("scope=assigned") == {held.id}


def test_plain_users_cannot_switch_scope(client, user_factory, login, ticket_factory):
    me = user_factory(username="mv-plain")
    mine = ticket_factory(me)
    login(client, me)

    html = client.get("/tickets/mine?scope=assigned").get_data(as_text=True)
    assert _row_ids(html) == [mine.id]
    assert "Opened by me" not in html


def test_search_and_fresh_mark(app, client, user_factory, login, ticket_factory):
    me = user_factory(username="mv-search")
    printer = ticket_factory(me, subject="Printer jam")
    vpn = ticket_factory(me, subject="VPN down")
    with app.app_context():
        db.session.add(
            Notification(user_id=me.id, ticket_id=vpn.id, message="x", url="/", is_read=False)
        )
        db.session.commit()
    login(client, me)

    assert _row_ids(client.get("/tickets/mine?q=printer").get_data(as_text=True)) == [printer.id]
    assert _row_ids(client.get(f"/tickets/mine?q=%23{vpn.id}").get_data(as_text=True)) == [vpn.id]

    html = client.get("/tickets/mine").get_data(as_text=True)
    row = html[html.index(f"#{vpn.id}</a>") - 2000 : html.index(f"#{vpn.id}</a>")]
    assert "is-fresh" in row and "New update" in html
    assert html.count("New update") == 1


def test_mine_pages(client, user_factory, login, ticket_factory):
    me = user_factory(username="mv-pages")
    for n in range(MINE_PER_PAGE + 2):
        ticket_factory(me, subject=f"Bulk {n}")
    login(client, me)

    first = client.get("/tickets/mine").get_data(as_text=True)
    assert len(_row_ids(first)) == MINE_PER_PAGE
    assert 'rel="next"' in first
    assert len(_row_ids(client.get("/tickets/mine?page=2").get_data(as_text=True))) == 2


def test_no_tickets_shows_onboarding(client, user_factory, login):
    login(client, user_factory(username="mv-empty"))

    assert "Create your first ticket" in client.get("/tickets/mine").get_data(as_text=True)
