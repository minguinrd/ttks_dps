from datetime import date, datetime, time, timedelta

from flask import render_template, request
from flask_login import login_required

from app.extensions import db
from app.models import Category, Priority, Ticket, TicketStatus
from app.permissions import role_required
from app.reports import reports_bp
from app.reports.forms import ReportForm


def _parse_date(value: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` filter value; malformed input is ignored (no filter)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _summarize(tickets: list[Ticket]) -> dict:
    """Aggregate the report summary from the very list rendered in the table.

    Keys: ``total``; per-status counts ``open``/``assigned``/``resolved``/``closed``;
    zero-filled ``by_category``/``by_priority`` breakdowns; ``oldest_unassigned`` —
    the ``created_at`` of the oldest open ticket without an assignee (or ``None``).
    """
    summary = {
        "total": len(tickets),
        "open": 0,
        "assigned": 0,
        "resolved": 0,
        "closed": 0,
        "by_category": {category.value: 0 for category in Category},
        "by_priority": {priority.value: 0 for priority in Priority},
        "oldest_unassigned": None,
    }
    for ticket in tickets:
        summary[ticket.status] += 1
        summary["by_category"][ticket.category] += 1
        summary["by_priority"][ticket.priority] += 1
        if ticket.status == TicketStatus.open and ticket.assignee_id is None:
            oldest = summary["oldest_unassigned"]
            if oldest is None or ticket.created_at < oldest:
                summary["oldest_unassigned"] = ticket.created_at
    return summary


# Empty rule + prefix "/reports" serves exactly "/reports" (no trailing slash):
# the URL pinned by the spec and the navbar link.
@reports_bp.route("")
@login_required
@role_required("agent", "admin")
def index():
    form = ReportForm(formdata=request.args)
    query = db.select(Ticket)
    date_from = _parse_date(request.args.get("date_from", ""))
    if date_from:
        query = query.where(Ticket.created_at >= datetime.combine(date_from, time.min))
    date_to = _parse_date(request.args.get("date_to", ""))
    if date_to:
        # End date is inclusive: cover everything up to (but excluding) midnight after it.
        query = query.where(
            Ticket.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    status = request.args.get("status", "")
    if status:
        query = query.where(Ticket.status == status)
    category = request.args.get("category", "")
    if category:
        query = query.where(Ticket.category == category)
    priority = request.args.get("priority", "")
    if priority:
        query = query.where(Ticket.priority == priority)
    department_id = request.args.get("department_id", type=int)
    if department_id:
        query = query.where(Ticket.department_id == department_id)
    requester_id = request.args.get("requester_id", type=int)
    if requester_id:
        query = query.where(Ticket.requester_id == requester_id)
    tickets = db.session.scalars(query.order_by(Ticket.created_at.desc())).all()
    return render_template(
        "reports/index.html",
        form=form,
        tickets=tickets,
        summary=_summarize(tickets),
    )
