from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectChoice, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.extensions import db
from app.i18n import _
from app.models import Category, Priority


class TicketForm(FlaskForm):
    subject = StringField(_("Subject"), validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(_("Description"), validators=[DataRequired()])
    category_id = SelectField(_("Category"), validators=[DataRequired()], coerce=int)
    priority = SelectField(
        _("Priority"),
        validators=[DataRequired()],
        choices=[SelectChoice(choice.value, choice.name.title()) for choice in Priority],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The fixed enum option labels translate per request (literal keys);
        # the submitted values stay the raw enum values.
        priority_labels = {
            "low": _("Low"),
            "normal": _("Normal"),
            "high": _("High"),
            "urgent": _("Urgent"),
        }
        self.category_id.choices = [
            SelectChoice(category.id, category.name)
            for category in db.session.scalars(db.select(Category).order_by(Category.name))
        ]
        self.priority.choices = [
            SelectChoice(choice.value, priority_labels[choice.value]) for choice in Priority
        ]


class CommentForm(FlaskForm):
    body = TextAreaField(_("Comment"), validators=[DataRequired()])
    is_internal = BooleanField(_("Internal note (agents and admins only)"))


class ResolveForm(FlaskForm):
    resolution_note = TextAreaField(_("Resolution note"), validators=[DataRequired()])


class AssignForm(FlaskForm):
    # Choices are filled per request with ``(0, "Select an agent…")`` plus the agents.
    agent_id = SelectField(_("Assign to"), coerce=int, validators=[DataRequired()])


TicketEditForm = TicketForm
