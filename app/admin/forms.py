from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectChoice, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.extensions import db
from app.models import Department, Role, User


class AdminUserForm(FlaskForm):
    """Create or edit a user account.

    Pass ``edit_user`` when editing: the username is fixed then and the initial
    password only applies on create (the account is created active with a
    forced password change).
    """

    username = StringField("Username", validators=[DataRequired(), Length(max=80)])
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "Role",
        validators=[DataRequired()],
        choices=[SelectChoice(role.value, role.name.title()) for role in Role],
    )
    department = SelectField("Department", validators=[Optional()], choices=[], coerce=str)
    initial_password = PasswordField(
        "Initial password", validators=[Optional(), Length(min=8, max=128)]
    )
    submit = SubmitField("Save")

    def __init__(self, *args, edit_user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edit_user = edit_user
        departments = db.session.scalars(db.select(Department).order_by(Department.name)).all()
        self.department.choices = [("", "— none —")] + [
            (str(department.id), department.name) for department in departments
        ]
        if edit_user is not None:
            self.username.validators = [Optional(), Length(max=80)]
            self.initial_password.validators = [Optional()]
        else:
            self.initial_password.validators = [DataRequired(), Length(min=8, max=128)]

    def validate_username(self, field):
        if self.edit_user is not None:
            return
        existing = db.session.scalar(db.select(User).filter_by(username=field.data))
        if existing is not None:
            raise ValidationError("Username already taken.")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=8, max=128)]
    )
    confirm = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Reset password")


class DepartmentForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("Add department")

    def validate_name(self, field):
        existing = db.session.scalar(db.select(Department).filter_by(name=field.data))
        if existing is not None:
            raise ValidationError("Department name already taken.")
