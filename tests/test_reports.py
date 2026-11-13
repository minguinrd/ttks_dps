import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CSS = Path(__file__).resolve().parents[1] / "app" / "static" / "css"


def _text(html):
    """Page text with tags stripped and whitespace collapsed.

    Lets the summary assertions pair each label with its count
    (``"Total 5"``) without depending on the exact markup around them.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_reports_requires_agent(app, client, user_factory, login):
    user = user_factory(role="user")
    login(client, user)

    resp = client.get("/reports")

    assert resp.status_code == 403

    resp = app.test_client().get("/reports")

    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_reports_renders_summary_and_list(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(username="reports-req")
    ticket_factory(requester, subject="PRINTER-ON-FIRE", category="hardware", priority="high")
    ticket_factory(requester, subject="MAIL-BOUNCES", category="software", priority="normal")
    ticket_factory(
        requester,
        subject="VPN-DROPS",
        category="hardware",
        priority="low",
        status="assigned",
        assignee=agent,
    )
    ticket_factory(
        requester,
        subject="PASSWORD-RESET",
        category="other",
        priority="urgent",
        status="resolved",
        assignee=agent,
    )
    ticket_factory(
        requester, subject="OLD-MONITOR", category="network", priority="normal", status="closed"
    )
    login(client, agent)

    resp = client.get("/reports")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    subjects = ("PRINTER-ON-FIRE", "MAIL-BOUNCES", "VPN-DROPS", "PASSWORD-RESET", "OLD-MONITOR")
    for subject in subjects:
        assert subject in html
    text = _text(html)
    assert "Total 5" in text
    assert "Open 2" in text
    assert "Assigned 1" in text
    assert "Resolved 1" in text
    assert "Closed 1" in text
    assert "hardware 2" in text
    assert "normal 2" in text


def test_reports_date_filter_scopes_summary(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(username="reports-dates-req")
    # SQLite hands back naive UTC datetimes; seed in the same shape.
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    ticket_factory(requester, subject="OLD-THREE-DAYS", created_at=now - timedelta(days=3))
    ticket_factory(
        requester,
        subject="TODAY-AT-2359",
        # On the end date itself, late at night: must not fall off the range.
        created_at=now.replace(hour=23, minute=59, second=0),
    )
    ticket_factory(requester, subject="OLD-TEN-DAYS", created_at=now - timedelta(days=10))
    login(client, agent)
    date_from = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")

    resp = client.get(f"/reports?date_from={date_from}&date_to={date_to}")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "TODAY-AT-2359" in html
    assert "OLD-THREE-DAYS" not in html
    assert "OLD-TEN-DAYS" not in html
    assert "Total 1" in _text(html)


def test_reports_status_filter(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(username="reports-status-req")
    ticket_factory(requester, subject="STILL-OPEN", status="open")
    ticket_factory(requester, subject="ALREADY-CLOSED", status="closed")
    login(client, agent)

    resp = client.get("/reports?status=open")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "STILL-OPEN" in html
    assert "ALREADY-CLOSED" not in html


def test_reports_page_declares_landscape_page(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(role="user", username="reports-landscape-req")
    ticket = ticket_factory(requester, subject="LANDSCAPE-TICKET")
    login(client, agent)

    reports_html = client.get("/reports").get_data(as_text=True)

    assert "size: A4 landscape" in reports_html
    # The override must be declared after the print.css link to win the cascade.
    assert reports_html.index("print.css") < reports_html.index("size: A4 landscape")

    login(client, requester)

    detail_html = client.get(f"/tickets/{ticket.id}").get_data(as_text=True)
    assert "size: A4 landscape" not in detail_html


def test_print_button_present(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(role="user", username="reports-print-req")
    ticket = ticket_factory(requester, subject="PRINTABLE-TICKET")
    login(client, agent)

    assert "window.print()" in client.get("/reports").get_data(as_text=True)

    login(client, requester)

    assert "window.print()" in client.get(f"/tickets/{ticket.id}").get_data(as_text=True)


def test_print_css_linked(client, user_factory, login):
    user = user_factory(role="user")
    login(client, user)

    resp = client.get("/", follow_redirects=True)

    assert resp.status_code == 200
    assert "print.css" in resp.get_data(as_text=True)


def test_print_css_fit_rules():
    css = (_CSS / "print.css").read_text(encoding="utf-8")

    # Pagination basics must survive any edit to the fit rules.
    assert "table-header-group" in css
    assert "page-break-inside: avoid" in css
    # Compact landscape table.
    assert "font-size: 9pt" in css
    # Cards avoid breaks, but only the summary/breakdown rows — the ticket
    # table's own card must stay free to paginate across pages.
    assert ".printable .row" in css
    assert ".printable .card {" not in css


def test_print_css_portrait_default_kept():
    css = (_CSS / "print.css").read_text(encoding="utf-8")

    # Landscape lives only in the reports page's page_css block, never here:
    # this file serves the ticket-detail printout too.
    assert "size: A4" in css
    assert "landscape" not in css


def test_phone_table_rules_screen_only():
    css = (_CSS / "main.css").read_text(encoding="utf-8")

    # Print viewports can match a bare max-width query; the stacked-phone
    # table must never trigger when printing.
    assert "@media screen and (max-width: 767.98px)" in css
    assert "@media (max-width: 767.98px)" not in css


def test_detail_print_hides_forms(client, user_factory, login, ticket_factory):
    agent = user_factory(role="agent")
    requester = user_factory(role="user", username="reports-clean-req")
    ticket = ticket_factory(requester, subject="CLEAN-PRINT", status="assigned", assignee=agent)

    for viewer in (agent, requester):
        login(client, viewer)
        html = client.get(f"/tickets/{ticket.id}").get_data(as_text=True)

        assert "window.print()" in html
        # Every form in the page body must be print-hidden so the printed
        # ticket shows only header, thread and resolution. The navbar's logout
        # form sits before <main> and is hidden wholesale by the .navbar rule.
        forms = re.findall(r"<form[^>]*>", html.split("<main", 1)[1])
        assert forms
        for form in forms:
            assert "no-print" in form, f"interactive form prints with the page: {form}"
