from flask_wtf import FlaskForm
from wtforms import DateField, SelectChoice, SelectField
from wtforms.validators import Optional

from app.extensions import db
from app.i18n import _
from app.models import Category, Department, Priority, TicketStatus, User


def _enum_choices(enum_cls):
    """``Any`` (empty = no filter) plus one option per enum value, like the ticket form."""
    return [SelectChoice("", "Any")] + [
        SelectChoice(choice.value, choice.name.title()) for choice in enum_cls
    ]


class ReportForm(FlaskForm):
    """GET filter form for the reports page; an empty value means "no filter"."""

    date_from = DateField(_("From"), validators=[Optional()])
    date_to = DateField(_("To"), validators=[Optional()])
    status = SelectField(_("Status"), validators=[Optional()], choices=_enum_choices(TicketStatus))
    category = SelectField(_("Category"), validators=[Optional()], choices=_enum_choices(Category))
    priority = SelectField(_("Priority"), validators=[Optional()], choices=_enum_choices(Priority))
    department_id = SelectField(_("Department"), validators=[Optional()])
    requester_id = SelectField(_("Requester"), validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Department/requester lists are built per request, like the queue filters.
        self.department_id.choices = [SelectChoice("", _("Any"))] + [
            SelectChoice(department.id, department.name)
            for department in db.session.scalars(db.select(Department).order_by(Department.name))
        ]
        self.requester_id.choices = [SelectChoice("", _("Any"))] + [
            SelectChoice(user.id, user.full_name or user.username)
            for user in db.session.scalars(db.select(User).order_by(User.username))
        ]
        # The fixed enum option labels translate per request (literal keys);
        # the submitted values stay the raw enum values.
        status_labels = {
            "open": _("Open"),
            "assigned": _("Assigned"),
            "resolved": _("Resolved"),
            "closed": _("Closed"),
        }
        category_labels = {
            "hardware": _("Hardware"),
            "software": _("Software"),
            "network": _("Network"),
            "access": _("Access"),
            "other": _("Other"),
        }
        priority_labels = {
            "low": _("Low"),
            "normal": _("Normal"),
            "high": _("High"),
            "urgent": _("Urgent"),
        }
        self.status.choices = [SelectChoice("", _("Any"))] + [
            SelectChoice(choice.value, status_labels[choice.value]) for choice in TicketStatus
        ]
        self.category.choices = [SelectChoice("", _("Any"))] + [
            SelectChoice(choice.value, category_labels[choice.value]) for choice in Category
        ]
        self.priority.choices = [SelectChoice("", _("Any"))] + [
            SelectChoice(choice.value, priority_labels[choice.value]) for choice in Priority
        ]
