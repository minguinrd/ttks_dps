"""Detailed report figures: resolution times, workload, aging, trend, CSV export."""

import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.durations import format_duration, resolution_time
from app.reports.stats import backlog_aging, trend


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _now():
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _ticket(status, created, resolved=None):
    return SimpleNamespace(status=status, created_at=created, resolved_at=resolved)


def test_resolution_time_ignores_reopened_tickets():
    created = datetime(2026, 1, 1, 9, 0)
    resolved = created + timedelta(hours=5)

    assert resolution_time(_ticket("resolved", created, resolved)) == timedelta(hours=5)
    assert resolution_time(_ticket("closed", created, resolved)) == timedelta(hours=5)
    # Reopened: back in the backlog with a stale resolved_at.
    assert resolution_time(_ticket("assigned", created, resolved)) is None
    assert resolution_time(_ticket("closed", created)) is None


def test_format_duration(app):
    with app.test_request_context():
        assert format_duration(None) == "—"
        assert format_duration(timedelta(minutes=45)) == "45 min"
        assert format_duration(timedelta(hours=5, minutes=59)) == "5 h"
        assert format_duration(timedelta(days=3, hours=4)) == "3 d 4 h"


def test_backlog_aging_counts_only_pending(app):
    now = datetime(2026, 6, 30, 12, 0)
    tickets = [
        _ticket("open", now - timedelta(hours=2)),
        _ticket("assigned", now - timedelta(days=2)),
        _ticket("open", now - timedelta(days=40)),
        _ticket("closed", now - timedelta(days=40)),
    ]
    with app.test_request_context():
        counts = [count for _label, count in backlog_aging(tickets, now)]

    assert counts == [1, 1, 0, 0, 1]


def test_trend_unit_follows_the_span(app):
    today = date(2026, 6, 30)
    with app.test_request_context():
        unit, rows = trend([], date(2026, 6, 1), date(2026, 6, 30), today)
        assert unit == "day"
        assert len(rows) == 30
        unit, _rows = trend([], date(2026, 3, 1), date(2026, 6, 30), today)
        assert unit == "week"
        unit, rows = trend([], date(2025, 7, 1), date(2026, 6, 30), today)
        assert unit == "month"
        assert len(rows) == 12
        assert trend([], None, None, today) == ("day", [])


def test_trend_counts_created_and_resolved_per_day(app):
    day = datetime(2026, 6, 10, 10, 0)
    tickets = [
        _ticket("resolved", day, day + timedelta(days=1)),
        _ticket("open", day),
    ]
    with app.test_request_context():
        _unit, rows = trend(tickets, date(2026, 6, 10), date(2026, 6, 12), date(2026, 6, 30))

    assert [(r.created, r.resolved) for r in rows] == [(2, 0), (0, 1), (0, 0)]


def test_report_shows_agent_workload_and_resolution_time(
    client, user_factory, login, ticket_factory
):
    agent = user_factory(role="agent", username="report-agent", full_name="Ana Agent")
    requester = user_factory(username="report-detail-req")
    now = _now()
    ticket_factory(
        requester,
        subject="FAST-FIX",
        status="resolved",
        assignee=agent,
        created_at=now - timedelta(hours=7),
        resolved_at=now - timedelta(hours=4),
    )
    ticket_factory(requester, subject="IN-PROGRESS", status="assigned", assignee=agent)
    ticket_factory(requester, subject="WAITING", created_at=now - timedelta(days=10))
    login(client, agent)

    text = _text(client.get("/reports").get_data(as_text=True))

    assert "Ana Agent 2 1 1 3 h" in text
    assert "Median time to resolve 3 h" in text
    assert "Resolution rate 33 %" in text
    assert "Pending 2" in text
    assert "7–30 days 1" in text
    assert "No department 3" in text


def test_report_lists_active_filters_and_presets(client, user_factory, login):
    agent = user_factory(role="agent")
    login(client, agent)

    html = client.get("/reports?status=open&date_from=2026-01-01").get_data(as_text=True)
    text = _text(html)

    assert "Status: Open" in text
    assert "From: 2026-01-01" in text
    assert "Last 30 days" in text
    # Presets keep the other filters.
    assert re.search(r'href="/reports\?status=open&amp;date_from=[\d-]+&amp;date_to=', html)
    assert 'href="/reports/export.csv?' in html


def test_csv_export_requires_agent(app, client, user_factory, login):
    login(client, user_factory(role="user"))

    assert client.get("/reports/export.csv").status_code == 403
    assert app.test_client().get("/reports/export.csv").status_code == 302


def test_csv_export_honours_filters_and_neutralises_formulas(
    client, user_factory, login, ticket_factory
):
    agent = user_factory(role="agent")
    requester = user_factory(username="csv-req")
    now = _now()
    ticket_factory(
        requester,
        subject="=HYPERLINK(evil)",
        status="resolved",
        assignee=agent,
        created_at=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=1, minutes=30),
    )
    ticket_factory(requester, subject="CLOSED-ONE", status="closed")
    login(client, agent)

    resp = client.get("/reports/export.csv?status=resolved")

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert rows[0][:3] == ["#", "Subject", "Status"]
    assert len(rows) == 2
    assert rows[1][1] == "'=HYPERLINK(evil)"
    assert rows[1][2] == "resolved"
    assert rows[1][-1] == "1.5"
