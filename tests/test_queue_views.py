"""Queue: pending-by-default tabs, assignee filter, search, sorting, paging."""

import re
from datetime import UTC, datetime, timedelta

from app.tickets.routes import QUEUE_PER_PAGE


def _row_ids(html):
    return [int(n) for n in re.findall(r">#(\d+)</a>", html)]


def _now():
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def test_default_tab_shows_only_pending_work(client, user_factory, login, ticket_factory):
    agent = user_factory(username="qv-agent", role="agent")
    owner = user_factory(username="qv-owner")
    waiting = ticket_factory(owner, status="open")
    working = ticket_factory(owner, status="assigned", assignee=agent)
    done = ticket_factory(owner, status="resolved", assignee=agent)
    shut = ticket_factory(owner, status="closed")
    login(client, agent)

    html = client.get("/tickets/queue").get_data(as_text=True)
    assert set(_row_ids(html)) == {waiting.id, working.id}
    assert re.search(r'aria-current="page"\s*>Pending <span class="count">2</span>', html)

    html = client.get("/tickets/queue?status=all").get_data(as_text=True)
    assert set(_row_ids(html)) == {waiting.id, working.id, done.id, shut.id}

    # Unknown tabs fall back to the default instead of matching nothing.
    html = client.get("/tickets/queue?status=bogus").get_data(as_text=True)
    assert set(_row_ids(html)) == {waiting.id, working.id}


def test_assignee_filter(client, user_factory, login, ticket_factory):
    me = user_factory(username="qv-me", role="agent")
    other = user_factory(username="qv-other", role="agent")
    owner = user_factory(username="qv-owner2")
    mine = ticket_factory(owner, status="assigned", assignee=me)
    theirs = ticket_factory(owner, status="assigned", assignee=other)
    nobody = ticket_factory(owner, status="open")
    login(client, me)

    def ids(query):
        return set(_row_ids(client.get(f"/tickets/queue?{query}").get_data(as_text=True)))

    assert ids("assignee=me") == {mine.id}
    assert ids("assignee=none") == {nobody.id}
    assert ids(f"assignee={other.id}") == {theirs.id}


def test_search_by_text_and_number(client, user_factory, login, ticket_factory):
    agent = user_factory(username="qv-search", role="agent")
    owner = user_factory(username="qv-owner3")
    printer = ticket_factory(owner, subject="Printer jam", description="Paper stuck")
    vpn = ticket_factory(owner, subject="VPN down", description="No tunnel to 100% office")
    login(client, agent)

    def ids(q):
        return set(
            _row_ids(client.get("/tickets/queue", query_string={"q": q}).get_data(as_text=True))
        )

    assert ids("printer") == {printer.id}
    assert ids("tunnel") == {vpn.id}
    assert ids(f"#{vpn.id}") == {vpn.id}
    # LIKE wildcards are literal: "%" only matches the ticket that contains one.
    assert ids("%") == {vpn.id}


def test_default_sort_is_priority_then_oldest(client, user_factory, login, ticket_factory):
    agent = user_factory(username="qv-sort", role="agent")
    owner = user_factory(username="qv-owner4")
    now = _now()
    low_old = ticket_factory(owner, priority="low", created_at=now - timedelta(days=9))
    urgent_new = ticket_factory(owner, priority="urgent", created_at=now - timedelta(hours=1))
    normal_old = ticket_factory(owner, priority="normal", created_at=now - timedelta(days=5))
    normal_new = ticket_factory(owner, priority="normal", created_at=now - timedelta(days=1))
    login(client, agent)

    html = client.get("/tickets/queue").get_data(as_text=True)
    assert _row_ids(html) == [urgent_new.id, normal_old.id, normal_new.id, low_old.id]

    html = client.get("/tickets/queue?sort=newest").get_data(as_text=True)
    assert _row_ids(html) == [urgent_new.id, normal_new.id, normal_old.id, low_old.id]


def test_queue_pages(client, user_factory, login, ticket_factory):
    agent = user_factory(username="qv-pages", role="agent")
    owner = user_factory(username="qv-owner5")
    for n in range(QUEUE_PER_PAGE + 3):
        ticket_factory(owner, subject=f"Bulk {n}")
    login(client, agent)

    first = client.get("/tickets/queue").get_data(as_text=True)
    assert len(_row_ids(first)) == QUEUE_PER_PAGE
    assert f"Showing 1–{QUEUE_PER_PAGE} of {QUEUE_PER_PAGE + 3}" in first
    assert 'rel="next"' in first

    second = client.get("/tickets/queue?page=2").get_data(as_text=True)
    assert len(_row_ids(second)) == 3
    assert 'rel="prev"' in second

    # Past the end: an empty page, not an error.
    assert client.get("/tickets/queue?page=99").status_code == 200
