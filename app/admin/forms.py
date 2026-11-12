from pathlib import Path

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from werkzeug.utils import secure_filename
from wtforms import PasswordField, SelectChoice, SelectField, StringField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    Regexp,
    ValidationError,
)

from app.extensions import db
from app.models import Department, Role, User

LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
LOGO_TOO_LARGE_ERROR = "File too large (max 2 MB)."


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
    """Create or rename a department.

    Pass ``edit_department`` when renaming: the duplicate check then skips the
    row being edited, so the department may keep its own name.
    """

    name = StringField("Name", validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("Add department")

    def __init__(self, *args, edit_department: Department | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edit_department = edit_department
        if edit_department is not None:
            self.submit.label.text = "Save"

    def validate_name(self, field):
        existing = db.session.scalar(db.select(Department).filter_by(name=field.data))
        if existing is None:
            return
        # Renaming keeps the current name valid: only *other* rows collide.
        if self.edit_department is not None and existing.id == self.edit_department.id:
            return
        raise ValidationError("Department name already taken.")


class BrandingForm(FlaskForm):
    """Deploy-wide branding: site name, accent color, and an optional logo."""

    site_name = StringField("Site name", validators=[DataRequired(), Length(max=100)])
    accent_color = StringField(
        "Accent color",
        validators=[Regexp(r"^#[0-9a-fA-F]{6}$", message="Use a hex color like #123456.")],
    )
    logo = FileField("Logo")
    submit = SubmitField("Save")

    def validate_logo(self, field):
        # Optional: nothing to check unless a file was submitted.
        if not field.data or not field.data.filename:
            return
        ext = Path(secure_filename(field.data.filename)).suffix.lower()
        if ext not in LOGO_EXTENSIONS:
            raise ValidationError("Unsupported image type. Use PNG, JPG, JPEG or SVG.")
        # Peek at the size, then rewind so the route can save the whole file.
        size = field.data.content_length or len(field.data.read())
        field.data.stream.seek(0)
        if size > 2 * 1024 * 1024:
            raise ValidationError(LOGO_TOO_LARGE_ERROR)
