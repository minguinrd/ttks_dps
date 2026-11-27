import csv
import io
from datetime import date, datetime, time, timedelta

from flask import Response, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.i18n import _
from app.models import Category, Ticket
from app.permissions import role_required
from app.reports import reports_bp
from app.reports.forms import ReportForm
from app.reports.stats import build_report, format_duration, naive_utc_now, resolution_time

# Query parameters the filter form owns, in display order.
FILTER_PARAMS = (
    "date_from",
    "date_to",
    "status",
    "category_id",
    "priority",
    "department_id",
    "requester_id",
)


def _parse_date(value: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` filter value; malformed input is ignored (no filter)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _filtered(args) -> tuple[list[Ticket], date | None, date | None]:
    """The tickets matching the filter query params, newest first."""
    query = Ticket.list_query()
    date_from = _parse_date(args.get("date_from", ""))
    if date_from:
        query = query.where(Ticket.created_at >= datetime.combine(date_from, time.min))
    date_to = _parse_date(args.get("date_to", ""))
    if date_to:
        # End date is inclusive: cover everything up to (but excluding) midnight after it.
        query = query.where(
            Ticket.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    if status := args.get("status", ""):
        query = query.where(Ticket.status == status)
    if category_id := args.get("category_id", type=int):
        query = query.where(Ticket.category_id == category_id)
    if priority := args.get("priority", ""):
        query = query.where(Ticket.priority == priority)
    if department_id := args.get("department_id", type=int):
        query = query.where(Ticket.department_id == department_id)
    if requester_id := args.get("requester_id", type=int):
        query = query.where(Ticket.requester_id == requester_id)
    tickets = db.session.scalars(query.order_by(Ticket.created_at.desc())).all()
    return list(tickets), date_from, date_to


def _active_filters(form: ReportForm, args) -> list[tuple[str, str]]:
    """``(label, value)`` for each applied filter, so a printout says what it covers."""
    applied = []
    for name in FILTER_PARAMS:
        raw = args.get(name, "")
        if not raw:
            continue
        field = form[name]
        if hasattr(field, "choices") and field.choices:
            labels = {str(choice.value): choice.label for choice in field.choices}
            if raw not in labels:
                continue
            applied.append((_(field.label.text), labels[raw]))
        elif _parse_date(raw):
            applied.append((_(field.label.text), raw))
    return applied


def _presets(args, today: date) -> list[dict]:
    """Quick date ranges that keep every other filter as it is."""
    kept = {
        k: v for k, v in args.items() if k in FILTER_PARAMS and k not in ("date_from", "date_to")
    }
    ranges = [
        (_("Last 7 days"), today - timedelta(days=6)),
        (_("Last 30 days"), today - timedelta(days=29)),
        (_("Last 90 days"), today - timedelta(days=89)),
        (_("This year"), today.replace(month=1, day=1)),
    ]
    current = (args.get("date_from", ""), args.get("date_to", ""))
    presets = []
    for label, start in ranges:
        span = (start.isoformat(), today.isoformat())
        presets.append(
            {
                "label": label,
                "url": url_for("reports.index", **kept, date_from=span[0], date_to=span[1]),
                "active": current == span,
            }
        )
    return presets


# Empty rule + prefix "/reports" serves exactly "/reports" (no trailing slash):
# the URL pinned by the spec and the navbar link.
@reports_bp.route("")
@login_required
@role_required("agent", "admin")
def index():
    form = ReportForm(formdata=request.args)
    tickets, date_from, date_to = _filtered(request.args)
    now = naive_utc_now()
    categories = list(db.session.scalars(db.select(Category.name).order_by(Category.name)))
    report = build_report(tickets, categories, date_from=date_from, date_to=date_to, now=now)
    query = {k: v for k, v in request.args.items() if k in FILTER_PARAMS and v}
    return render_template(
        "reports/index.html",
        form=form,
        tickets=tickets,
        report=report,
        now=now,
        filters=_active_filters(form, request.args),
        presets=_presets(request.args, now.date()),
        export_url=url_for("reports.export_csv", **query),
        duration=format_duration,
        resolution_time=resolution_time,
    )


# Spreadsheet apps execute cells that start with these characters.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _stamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


@reports_bp.route("/export.csv")
@login_required
@role_required("agent", "admin")
def export_csv():
    """The filtered ticket list as CSV (UTF-8 with BOM so Excel reads accents)."""
    tickets, _date_from, _date_to = _filtered(request.args)
    status_labels = {
        "open": _("open"),
        "assigned": _("assigned"),
        "resolved": _("resolved"),
        "closed": _("closed"),
    }
    priority_labels = {
        "low": _("low"),
        "normal": _("normal"),
        "high": _("high"),
        "urgent": _("urgent"),
    }
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "#",
            _("Subject"),
            _("Status"),
            _("Priority"),
            _("Category"),
            _("Department"),
            _("Requester"),
            _("Assignee"),
            _("Created"),
            _("Resolved"),
            _("Closed"),
            _("Hours to resolve"),
        ]
    )
    for ticket in tickets:
        took = resolution_time(ticket)
        writer.writerow(
            [
                ticket.id,
                _cell(ticket.subject),
                status_labels.get(ticket.status, ticket.status),
                priority_labels.get(ticket.priority, ticket.priority),
                _cell(ticket.category.name),
                _cell(ticket.department.name if ticket.department else ""),
                _cell(ticket.requester.full_name or ticket.requester.username),
                _cell(
                    (ticket.assignee.full_name or ticket.assignee.username)
                    if ticket.assignee
                    else ""
                ),
                _stamp(ticket.created_at),
                _stamp(ticket.resolved_at),
                _stamp(ticket.closed_at),
                f"{took.total_seconds() / 3600:.1f}" if took is not None else "",
            ]
        )
    filename = f"tickets-{naive_utc_now():%Y%m%d-%H%M}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
