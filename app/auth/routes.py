from flask import current_app, flash, redirect, render_template, url_for
from flask_login import login_required, login_user, logout_user

from app.auth import auth_bp
from app.auth.forms import LoginForm, RegisterForm
from app.auth.google_login import find_or_create_google_user
from app.extensions import db, oauth
from app.models import Role, User
from app.notifications import notify

# Pinned refusal strings (shared by the password and Google login paths).
PENDING_MESSAGE = "Your account is awaiting admin approval."
SUSPENDED_MESSAGE = "This account has been suspended. Contact the administrator."
# Generic message for every Google sign-in failure (config missing, bad state,
# unverified email, identity conflict, third-party errors): never leak which.
GOOGLE_FAILURE_MESSAGE = (
    "Google sign-in failed. Please try again or use your username and password."
)


def _google_configured() -> bool:
    return bool(
        current_app.config["GOOGLE_CLIENT_ID"] and current_app.config["GOOGLE_CLIENT_SECRET"]
    )


def _google_failure():
    flash(GOOGLE_FAILURE_MESSAGE, "danger")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            full_name=form.full_name.data,
            email=form.email.data,
            department_id=int(form.department.data) if form.department.data else None,
            status="pending",
            role="user",
        )
        user.set_password(form.password.data)
        db.session.add(user)
        # Every new pending registration pings all admins (the /admin/ panel
        # is where approvals happen).
        admin_ids = db.session.scalars(db.select(User.id).where(User.role == Role.admin)).all()
        notify(
            admin_ids,
            f"New user {user.username} is awaiting approval.",
            "/admin/",
        )
        db.session.commit()
        return redirect(url_for("auth.pending"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/pending")
def pending():
    return render_template("auth/pending.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).filter_by(username=form.username.data))
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.", "danger")
        elif user.status == "pending":
            flash(PENDING_MESSAGE, "warning")
        elif user.status == "suspended":
            flash(SUSPENDED_MESSAGE, "danger")
        else:
            login_user(user)
            return redirect(url_for("main.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/google")
def google():
    if not _google_configured():
        return _google_failure()
    google_client = oauth.create_client("google")
    return google_client.authorize_redirect(url_for("auth.google_callback", _external=True))


@auth_bp.route("/google/callback")
def google_callback():
    if not _google_configured():
        return _google_failure()
    google_client = oauth.create_client("google")
    try:
        # Plan-mandated third-party/error boundary: the token exchange, the
        # userinfo parsing and the account matching all collapse into the one
        # generic failure flash (identity conflicts included) instead of a 500.
        token = google_client.authorize_access_token()
        userinfo = token.get("userinfo") or google_client.parse_id_token(token)
        if not (userinfo.get("email_verified") and userinfo.get("sub") and userinfo.get("email")):
            return _google_failure()
        user, _created = find_or_create_google_user(
            userinfo["email"], sub=userinfo["sub"], name=userinfo.get("name")
        )
    except Exception:
        return _google_failure()
    # The status gate sits outside the try: refusals show their specific
    # pinned message, and only active accounts get a session.
    if user.status == "pending":
        flash(PENDING_MESSAGE, "warning")
        return redirect(url_for("auth.pending"))
    if user.status == "suspended":
        flash(SUSPENDED_MESSAGE, "danger")
        return redirect(url_for("auth.login"))
    login_user(user)
    return redirect(url_for("main.index"))


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
