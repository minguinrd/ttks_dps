from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectChoice, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.models import Category, Priority


class TicketForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[DataRequired()])
    category = SelectField(
        "Category",
        validators=[DataRequired()],
        choices=[SelectChoice(choice.value, choice.name.title()) for choice in Category],
    )
    priority = SelectField(
        "Priority",
        validators=[DataRequired()],
        choices=[SelectChoice(choice.value, choice.name.title()) for choice in Priority],
    )


class CommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired()])
    is_internal = BooleanField("Internal note (agents and admins only)")


TicketEditForm = TicketForm
