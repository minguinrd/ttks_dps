"""Admin dashboard action list, workload, system facts; user search."""

import os
import re
import time
from datetime import UTC, datetime, timedelta

import pytest


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture()
def backup_dir(app, tmp_path, monkeypatch):
    """A private, empty BACKUP_DIR (the app fixture's one is shared)."""
    path = tmp_path / "backups"
    path.mkdir()
    monkeypatch.setitem(app.config, "BACKUP_DIR", str(path))
    return path


def _now():
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def test_dashboard_all_clear_with_fresh_backup(client, user_factory, login, backup_dir):
    admin = user_factory(username="dash-clear", role="admin")
    (backup_dir / "ttks_dps-20260101-030000.db").write_bytes(b"x")
    login(client, admin)

    text = _text(client.get("/admin/").get_data(as_text=True))

    assert "Nothing needs attention right now." in text
    assert "Google sign-in Off" in text


def test_dashboard_flags_what_needs_action(client, user_factory, login, ticket_factory, backup_dir):
    admin = user_factory(username="dash-admin", role="admin")
    gone = user_factory(username="dash-gone", role="agent", status="suspended")
    user_factory(username="dash-pending", full_name="Pat Pending", status="pending")
    requester = user_factory(username="dash-req")
    ticket_factory(
        requester, subject="WAITING-LONG", priority="urgent", created_at=_now() - timedelta(days=3)
    )
    ticket_factory(requester, subject="HELD-BY-GONE", status="assigned", assignee=gone)
    # Closed with a suspended assignee: nothing to do, must not be listed.
    ticket_factory(requester, subject="CLOSED-BY-GONE", status="closed", assignee=gone)
    login(client, admin)

    html = client.get("/admin/").get_data(as_text=True)
    text = _text(html)

    assert "1 registrations awaiting approval" in text
    assert "Pat Pending" in text
    assert "Oldest unassigned ticket: 3 d 0 h" in text
    assert "WAITING-LONG" in text
    assert "1 urgent tickets still pending" in text
    assert "Tickets with a stale assignee: 1" in text
    assert "HELD-BY-GONE" in text
    assert "CLOSED-BY-GONE" not in text.split("Team workload")[0]
    assert "No backups yet" in text


def test_dashboard_workload_counts_active_staff(client, user_factory, login, ticket_factory):
    admin = user_factory(username="dash-wl-admin", role="admin", full_name="Ada Admin")
    agent = user_factory(username="dash-wl-agent", role="agent", full_name="Bo Busy")
    requester = user_factory(username="dash-wl-req")
    for _ in range(2):
        ticket_factory(requester, status="assigned", assignee=agent)
    ticket_factory(
        requester, status="resolved", assignee=agent, resolved_at=_now() - timedelta(days=1)
    )
    login(client, admin)

    text = _text(client.get("/admin/").get_data(as_text=True))

    assert "Bo Busy 2 1" in text
    assert "Ada Admin 0 0" in text
    # Busiest first.
    assert text.index("Bo Busy 2 1") < text.index("Ada Admin 0 0")


def test_dashboard_warns_on_stale_backup(client, user_factory, login, backup_dir):
    admin = user_factory(username="dash-oldbackup", role="admin")
    old = backup_dir / "ttks_dps-20200101-030000.db"
    old.write_bytes(b"x")
    stamp = time.time() - 3 * 86400
    os.utime(old, (stamp, stamp))
    login(client, admin)

    text = _text(client.get("/admin/").get_data(as_text=True))

    assert "No backup in the last day" in text


def test_users_search_and_role_filter(client, user_factory, login):
    admin = user_factory(username="search-admin", role="admin")
    user_factory(username="maria-agent", full_name="María López", role="agent")
    user_factory(username="mario-user", email="mario@example.test")
    user_factory(username="other-person")
    login(client, admin)

    html = client.get("/admin/users?q=mari").get_data(as_text=True)
    assert "maria-agent" in html and "mario-user" in html
    assert "other-person" not in html
    # Tab counts honour the search.
    assert re.search(r"All <span class=\"count\">2</span>", html)

    html = client.get("/admin/users?q=mari&role=agent").get_data(as_text=True)
    assert "maria-agent" in html and "mario-user" not in html

    html = client.get("/admin/users?q=example.test").get_data(as_text=True)
    assert "mario-user" in html and "maria-agent" not in html


def test_users_search_treats_wildcards_literally(client, user_factory, login):
    admin = user_factory(username="wild-admin", role="admin")
    user_factory(username="plain-user")
    login(client, admin)

    html = client.get("/admin/users?q=%25").get_data(as_text=True)

    assert "plain-user" not in html
    assert "No users match this filter." in html
