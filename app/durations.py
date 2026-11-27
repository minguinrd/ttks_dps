"""Ticket durations shared by the ticket page, the dashboard and the reports."""

from datetime import timedelta

from app.i18n import _
from app.models import Ticket, TicketStatus

_BACKLOG = (TicketStatus.open, TicketStatus.assigned)


def resolution_time(ticket: Ticket) -> timedelta | None:
    """Created → resolved, for tickets that are currently resolved or closed.

    A reopened ticket keeps its old ``resolved_at``; it is back in the
    backlog, so it does not count as resolved until it is resolved again.
    """
    if ticket.resolved_at is None or ticket.status in _BACKLOG:
        return None
    return max(ticket.resolved_at - ticket.created_at, timedelta(0))


def format_duration(value: timedelta | None) -> str:
    """Compact, translated duration: ``45 min``, ``5 h``, ``3 d 4 h``."""
    if value is None:
        return "—"
    minutes = int(value.total_seconds() // 60)
    if minutes < 60:
        return _("{n} min", n=minutes)
    hours = minutes // 60
    if hours < 24:
        return _("{n} h", n=hours)
    return _("{d} d {h} h", d=hours // 24, h=hours % 24)
