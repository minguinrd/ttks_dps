from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.extensions import db
from app.models import Department, User


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    department = SelectField("Department", validators=[Optional()], choices=[], coerce=str)
    submit = SubmitField("Register")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        departments = db.session.scalars(db.select(Department).order_by(Department.name)).all()
        self.department.choices = [("", "— none —")] + [
            (str(department.id), department.name) for department in departments
        ]

    def validate_username(self, field):
        existing = db.session.scalar(db.select(User).filter_by(username=field.data))
        if existing is not None:
            raise ValidationError("Username already taken.")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")
