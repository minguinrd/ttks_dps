import os
from pathlib import Path

from flask import current_app
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import PasswordField, SelectChoice, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.i18n import _

AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
AVATAR_TOO_LARGE_ERROR = _("File too large (max 2 MB).")


class ProfileForm(FlaskForm):
    full_name = StringField(_("Full name"), validators=[DataRequired(), Length(max=120)])
    email = StringField(_("Email"), validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField(_("Save"))


class LanguageForm(FlaskForm):
    # Choice labels are language names shown in their own language (English,
    # Español) — deliberately untranslated.
    language = SelectField(
        _("Language"),
        choices=[SelectChoice("en", "English"), SelectChoice("es", "Español")],
        validators=[DataRequired()],
    )
    submit = SubmitField(_("Save"))


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(_("Current password"), validators=[DataRequired()])
    new_password = PasswordField(
        _("New password"), validators=[DataRequired(), Length(min=8, max=128)]
    )
    confirm = PasswordField(
        _("Confirm new password"),
        validators=[DataRequired(), EqualTo("new_password", message=_("Passwords must match."))],
    )
    submit = SubmitField(_("Change password"))

    def validate_current_password(self, field):
        if not current_user.check_password(field.data):
            raise ValidationError(_("Current password is incorrect."))


class AvatarForm(FlaskForm):
    avatar = FileField(_("Avatar"), validators=[FileRequired(message=_("Choose a file."))])
    submit = SubmitField(_("Upload"))

    def validate_avatar(self, field):
        ext = Path(field.data.filename or "").suffix.lower().lstrip(".")
        if ext not in AVATAR_EXTENSIONS:
            raise ValidationError(_("Unsupported image type. Use PNG, JPG, JPEG or WEBP."))
        if not field.data.mimetype.startswith("image/"):
            raise ValidationError(_("The uploaded file is not an image."))
        stream = field.data.stream
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size > current_app.config["MAX_CONTENT_LENGTH"]:
            raise ValidationError(AVATAR_TOO_LARGE_ERROR)
