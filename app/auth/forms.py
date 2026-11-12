from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.extensions import db
from app.i18n import _
from app.models import Department, User


class RegisterForm(FlaskForm):
    username = StringField(_("Username"), validators=[DataRequired(), Length(max=80)])
    password = PasswordField(_("Password"), validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        _("Confirm password"),
        validators=[DataRequired(), EqualTo("password", message=_("Passwords must match."))],
    )
    full_name = StringField(_("Full name"), validators=[DataRequired(), Length(max=120)])
    email = StringField(_("Email"), validators=[DataRequired(), Email(), Length(max=255)])
    department = SelectField(_("Department"), validators=[Optional()], choices=[], coerce=str)
    submit = SubmitField(_("Register"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        departments = db.session.scalars(db.select(Department).order_by(Department.name)).all()
        self.department.choices = [("", _("— none —"))] + [
            (str(department.id), department.name) for department in departments
        ]

    def validate_username(self, field):
        existing = db.session.scalar(db.select(User).filter_by(username=field.data))
        if existing is not None:
            raise ValidationError(_("Username already taken."))


class LoginForm(FlaskForm):
    username = StringField(_("Username"), validators=[DataRequired()])
    password = PasswordField(_("Password"), validators=[DataRequired()])
    submit = SubmitField(_("Sign in"))
