from pathlib import Path
from uuid import uuid4

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app.admin.forms import LOGO_TOO_LARGE_ERROR, BrandingForm
from app.branding import get_branding, get_setting
from app.extensions import db
from app.i18n import SUPPORTED, _
from app.main import main_bp
from app.main.forms import (
    AVATAR_TOO_LARGE_ERROR,
    AvatarForm,
    ChangePasswordForm,
    LanguageForm,
    ProfileForm,
)
from app.models import Notification, Role, User

LOGO_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


@main_bp.route("/")
@login_required
def index():
    # Hardcoded paths on purpose: the tickets routes land in a later task and
    # these exact paths are pinned by the spec, so no url_for here.
    if current_user.role == Role.user:
        return redirect("/tickets/mine")
    return redirect("/tickets/queue")


@main_bp.route("/notifications")
@login_required
def notifications():
    rows = db.session.scalars(
        db.select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    ).all()
    return render_template("main/notifications.html", notifications=rows)


@main_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        abort(404)
    notification.is_read = True
    db.session.commit()
    return redirect(notification.url)


@main_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    rows = db.session.scalars(
        db.select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    ).all()
    for row in rows:
        row.is_read = True
    db.session.commit()
    flash(_("All notifications marked as read."), "success")
    return redirect(url_for("main.notifications"))


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data
        current_user.email = form.email.data
        db.session.commit()
        flash(_("Profile updated."), "success")
        return redirect(url_for("main.profile"))
    return render_template(
        "main/profile.html",
        form=form,
        avatar_form=AvatarForm(),
        language_form=LanguageForm(formdata=None, obj=current_user),
    )


@main_bp.route("/profile/password", methods=["GET", "POST"])
@login_required
def profile_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_user.set_password(form.new_password.data)
        current_user.must_change_password = False
        db.session.commit()
        flash(_("Password changed."), "success")
        return redirect(url_for("main.index"))
    return render_template("main/profile_password.html", form=form)


@main_bp.route("/profile/language", methods=["POST"])
@login_required
def language_save():
    form = LanguageForm()
    if form.validate_on_submit() and form.language.data in SUPPORTED:
        current_user.language = form.language.data
        db.session.commit()
        flash(_("Language updated."), "success")
        return redirect(url_for("main.profile"))
    if not form.language.errors:
        form.language.errors = ["Not a valid choice."]
    return _render_profile(AvatarForm(), language_form=form)


@main_bp.route("/profile/avatar", methods=["POST"])
@login_required
def avatar_upload():
    form = AvatarForm()
    if form.validate_on_submit():
        avatar_dir = Path(current_app.config["AVATAR_DIR"])
        ext = Path(form.avatar.data.filename).suffix.lower().lstrip(".")
        filename = f"{uuid4().hex}.{ext}"
        old_path = current_user.avatar_path
        form.avatar.data.save(avatar_dir / filename)
        current_user.avatar_path = filename
        db.session.commit()
        if old_path:
            (avatar_dir / old_path).unlink(missing_ok=True)
        flash(_("Avatar updated."), "success")
        return redirect(url_for("main.profile"))
    return _render_profile(form)


@main_bp.route("/avatars/<int:user_id>")
@login_required
def serve_avatar(user_id):
    user = db.session.get(User, user_id)
    if user is None or not user.avatar_path:
        abort(404)
    return send_from_directory(current_app.config["AVATAR_DIR"], user.avatar_path)


@main_bp.route("/branding/logo")
def branding_logo():
    """Serve the deployed site logo; public, 404 until a logo is uploaded."""
    name = get_setting("logo_file")
    if not name or Path(name).name != name:
        # A missing or hostile ``logo_file`` row is treated as "no logo".
        abort(404)
    mimetype = LOGO_MIME_TYPES.get(Path(name).suffix.lower())
    if mimetype is None:
        abort(404)
    path = Path(current_app.config["DATA_DIR"]) / "branding" / name
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype=mimetype)


def _render_profile(avatar_form, language_form=None):
    """Render the profile page; the profile form is display-only here (no request body)."""
    if language_form is None:
        language_form = LanguageForm(formdata=None, obj=current_user)
    return render_template(
        "main/profile.html",
        form=ProfileForm(formdata=None, obj=current_user),
        avatar_form=avatar_form,
        language_form=language_form,
    )


def avatar_upload_error_response():
    """Friendly "file too large" page for an oversized avatar upload.

    Also used by the app-level 413 handler: with CSRF enabled the body is
    rejected while CSRF reads the parsed form (before_request), before the
    route ever runs.
    """
    avatar_form = AvatarForm(formdata=None)
    avatar_form.avatar.errors = [AVATAR_TOO_LARGE_ERROR]
    return _render_profile(avatar_form)


def branding_upload_error_response():
    """Friendly "file too large" page for an oversized branding logo upload.

    Also used by the app-level 413 handler: with CSRF enabled the body is
    rejected while CSRF reads the parsed form (before_request), before the
    route ever runs. No branding state is written, so the form just gets the
    inline size error and the current settings.
    """
    branding_form = BrandingForm(formdata=None)
    branding_form.logo.errors = [LOGO_TOO_LARGE_ERROR]
    branding = get_branding()
    branding_form.site_name.data = branding["site_name"]
    branding_form.accent_color.data = branding["accent_color"]
    return render_template("admin/branding.html", form=branding_form)
