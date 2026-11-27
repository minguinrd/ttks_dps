"""Report aggregation over an already-filtered ticket list.

Everything here is pure Python over the rows the page renders, so the figures
always agree with the ticket table underneath them. Datetimes are naive UTC,
the shape SQLite hands back.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.durations import resolution_time
from app.i18n import _
from app.models import Priority, Ticket, TicketStatus

# Status order used everywhere a report lists statuses.
STATUS_ORDER = (
    TicketStatus.open,
    TicketStatus.assigned,
    TicketStatus.resolved,
    TicketStatus.closed,
)
# Most to least pressing, the order the priority breakdown reads in.
PRIORITY_ORDER = (Priority.urgent, Priority.high, Priority.normal, Priority.low)
_BACKLOG = (TicketStatus.open, TicketStatus.assigned)


def naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


@dataclass
class Group:
    """One row of a breakdown table (a category, priority, agent...)."""

    label: str
    total: int = 0
    backlog: int = 0
    resolved: int = 0
    durations: list[timedelta] = field(default_factory=list)

    def add(self, ticket: Ticket) -> None:
        self.total += 1
        if ticket.status in _BACKLOG:
            self.backlog += 1
        took = resolution_time(ticket)
        if took is not None:
            self.resolved += 1
            self.durations.append(took)

    @property
    def median(self) -> timedelta | None:
        return statistics.median(self.durations) if self.durations else None

    @property
    def mean(self) -> timedelta | None:
        if not self.durations:
            return None
        return sum(self.durations, timedelta(0)) / len(self.durations)


@dataclass
class Bucket:
    start: date
    label: str
    title: str
    created: int = 0
    resolved: int = 0
    show_label: bool = True


def _period_of(day: date, unit: str) -> date:
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)
    return day


def _next_period(start: date, unit: str) -> date:
    if unit == "week":
        return start + timedelta(days=7)
    if unit == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=1)


def trend(
    tickets: list[Ticket], date_from: date | None, date_to: date | None, today: date
) -> tuple[str, list[Bucket]]:
    """Created and resolved counts per day, week or month across the period.

    The unit follows the span: up to a month by day, up to half a year by
    week, longer by month. Empty when there is nothing to plot.
    """
    if not tickets and not (date_from and date_to):
        return "day", []
    created_days = [t.created_at.date() for t in tickets]
    resolved_days = [t.resolved_at.date() for t in tickets if resolution_time(t) is not None]
    start = date_from or min(created_days)
    end = date_to or max([today, *resolved_days])
    if end < start:
        start, end = end, start
    span = (end - start).days + 1
    unit = "day" if span <= 31 else "week" if span <= 183 else "month"

    buckets: dict[date, Bucket] = {}
    cursor = _period_of(start, unit)
    while cursor <= end:
        if unit == "month":
            label, title = cursor.strftime("%m/%Y"), cursor.strftime("%m/%Y")
        elif unit == "week":
            label = cursor.strftime("%d/%m")
            title = _("Week of {day}", day=cursor.strftime("%Y-%m-%d"))
        else:
            label, title = cursor.strftime("%d/%m"), cursor.strftime("%Y-%m-%d")
        buckets[cursor] = Bucket(start=cursor, label=label, title=title)
        cursor = _next_period(cursor, unit)

    for day in created_days:
        bucket = buckets.get(_period_of(day, unit))
        if bucket:
            bucket.created += 1
    for day in resolved_days:
        bucket = buckets.get(_period_of(day, unit))
        if bucket:
            bucket.resolved += 1

    rows = list(buckets.values())
    # Keep roughly a dozen axis labels whatever the number of columns.
    step = max(1, -(-len(rows) // 12))
    for index, bucket in enumerate(rows):
        bucket.show_label = index % step == 0
    return unit, rows


# (upper bound in days, label) — the last bucket is open-ended.
_AGE_BUCKETS = (
    (1, "Under 1 day"),
    (3, "1–3 days"),
    (7, "3–7 days"),
    (30, "7–30 days"),
    (None, "Over 30 days"),
)


def backlog_aging(tickets: list[Ticket], now: datetime) -> list[tuple[str, int]]:
    """How long the open and in-progress tickets have been waiting."""
    labels = {
        "Under 1 day": _("Under 1 day"),
        "1–3 days": _("1–3 days"),
        "3–7 days": _("3–7 days"),
        "7–30 days": _("7–30 days"),
        "Over 30 days": _("Over 30 days"),
    }
    counts = Counter()
    for ticket in tickets:
        if ticket.status not in _BACKLOG:
            continue
        age_days = (now - ticket.created_at).total_seconds() / 86400
        for limit, key in _AGE_BUCKETS:
            if limit is None or age_days < limit:
                counts[key] += 1
                break
    return [(labels[key], counts[key]) for _limit, key in _AGE_BUCKETS]


def _display(user) -> str:
    return user.full_name or user.username


def build_report(
    tickets: list[Ticket],
    categories: list[str],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    now: datetime | None = None,
) -> dict:
    """Every figure the reports page shows, from the filtered ``tickets``.

    ``categories`` (all category names, sorted) zero-fills the category
    breakdown so empty categories still show up.
    """
    now = now or naive_utc_now()
    overall = Group(label="")
    by_status = Counter()
    by_priority = {p.value: Group(label=p.value) for p in PRIORITY_ORDER}
    by_category = {name: Group(label=name) for name in categories}
    by_department: dict[str, Group] = {}
    by_agent: dict[int, Group] = {}
    requesters = Counter()
    requester_names: dict[int, str] = {}
    oldest_unassigned: Ticket | None = None
    closed_unresolved = 0

    for ticket in tickets:
        overall.add(ticket)
        by_status[ticket.status] += 1
        by_priority.setdefault(ticket.priority, Group(label=ticket.priority)).add(ticket)
        name = ticket.category.name
        by_category.setdefault(name, Group(label=name)).add(ticket)
        department = ticket.department.name if ticket.department else _("No department")
        by_department.setdefault(department, Group(label=department)).add(ticket)
        if ticket.assignee is not None:
            agent = by_agent.setdefault(ticket.assignee.id, Group(label=_display(ticket.assignee)))
            agent.add(ticket)
        requesters[ticket.requester.id] += 1
        requester_names[ticket.requester.id] = _display(ticket.requester)
        if ticket.status == TicketStatus.closed and ticket.resolved_at is None:
            closed_unresolved += 1
        if (
            ticket.status == TicketStatus.open
            and ticket.assignee_id is None
            and (oldest_unassigned is None or ticket.created_at < oldest_unassigned.created_at)
        ):
            oldest_unassigned = ticket

    total = overall.total
    unit, buckets = trend(tickets, date_from, date_to, now.date())
    trend_max = max([1, *(max(b.created, b.resolved) for b in buckets)])

    def ranked(groups):
        return sorted(groups, key=lambda g: (-g.total, g.label.lower()))

    return {
        "total": total,
        "backlog": overall.backlog,
        "resolved": overall.resolved,
        "resolution_rate": round(overall.resolved / total * 100) if total else None,
        "median_resolution": overall.median,
        "mean_resolution": overall.mean,
        "closed_unresolved": closed_unresolved,
        "oldest_unassigned": oldest_unassigned,
        "oldest_unassigned_age": (now - oldest_unassigned.created_at)
        if oldest_unassigned
        else None,
        "status": [(status.value, by_status[status]) for status in STATUS_ORDER],
        "by_priority": list(by_priority.values()),
        "by_category": list(by_category.values()),
        "by_department": ranked(by_department.values()),
        "by_agent": ranked(by_agent.values()),
        "top_requesters": [
            (requester_names[user_id], count) for user_id, count in requesters.most_common(5)
        ],
        "aging": backlog_aging(tickets, now),
        "trend_unit": unit,
        "trend": buckets,
        "trend_max": trend_max,
    }
