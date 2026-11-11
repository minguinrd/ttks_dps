from flask_wtf import FlaskForm
from wtforms import DateField, SelectChoice, SelectField
from wtforms.validators import Optional

from app.extensions import db
from app.models import Category, Department, Priority, TicketStatus, User


def _enum_choices(enum_cls):
    """``Any`` (empty = no filter) plus one option per enum value, like the ticket form."""
    return [SelectChoice("", "Any")] + [
        SelectChoice(choice.value, choice.name.title()) for choice in enum_cls
    ]


class ReportForm(FlaskForm):
    """GET filter form for the reports page; an empty value means "no filter"."""

    date_from = DateField("From", validators=[Optional()])
    date_to = DateField("To", validators=[Optional()])
    status = SelectField("Status", validators=[Optional()], choices=_enum_choices(TicketStatus))
    category = SelectField("Category", validators=[Optional()], choices=_enum_choices(Category))
    priority = SelectField("Priority", validators=[Optional()], choices=_enum_choices(Priority))
    department_id = SelectField("Department", validators=[Optional()])
    requester_id = SelectField("Requester", validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Department/requester lists are built per request, like the queue filters.
        self.department_id.choices = [SelectChoice("", "Any")] + [
            SelectChoice(department.id, department.name)
            for department in db.session.scalars(db.select(Department).order_by(Department.name))
        ]
        self.requester_id.choices = [SelectChoice("", "Any")] + [
            SelectChoice(user.id, user.full_name or user.username)
            for user in db.session.scalars(db.select(User).order_by(User.username))
        ]
