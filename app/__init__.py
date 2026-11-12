import os

from flask import Flask, flash, g, redirect, request, url_for
from flask_login import current_user
from werkzeug.exceptions import Forbidden, RequestEntityTooLarge

from app import (
    backup,
    models,  # noqa: F401  # register ORM mappers so Flask-Migrate can autogenerate
)
from app.admin import admin_bp
from app.auth import auth_bp
from app.branding import get_branding
from app.cli import restore_backup, seed_admin
from app.config import Config
from app.extensions import csrf, db, login_manager, migrate, oauth
from app.i18n import SUPPORTED, _, translate
from app.main import main_bp
from app.main.routes import avatar_upload_error_response, branding_upload_error_response
from app.notifications import unread_count
from app.reports import reports_bp
from app.tickets import tickets_bp

# Endpoints a user with a pending forced password change may still reach.
PASSWORD_CHANGE_EXEMPT = {"static", "auth.logout", "main.profile_password"}
FORCED_PASSWORD_CHANGE_MESSAGE = _("You must change your password before continuing.")


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["AVATAR_DIR"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    oauth.init_app(app)
    # Google sign-in is fully env-gated: without both values the button is
    # hidden and the /auth/google routes refuse with a generic flash. The
    # GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET config keys double as Authlib's
    # client credentials (its GOOGLE_* load_config convention).
    if app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]:
        oauth.register(
            "google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp)

    # Daily backup scheduler (app/backup.py). Never while testing: the test
    # suite must not spawn its thread (see tests/test_scaffold.py).
    if not app.testing:
        backup.start_scheduler(app)

    app.cli.add_command(seed_admin)
    app.cli.add_command(restore_backup)

    @app.context_processor
    def inject_branding():
        # Deploy-wide branding (site name, accent color, logo) for every template.
        return {"branding": get_branding()}

    @app.context_processor
    def inject_notification_helpers():
        # Lets templates call ``unread_count(current_user)`` for the navbar badge.
        return {"unread_count": unread_count}

    @app.context_processor
    def inject_google_enabled():
        # Gates the "Sign in with Google" button on the login page.
        return {
            "google_enabled": bool(
                app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]
            )
        }

    # ``_`` resolves the locale per request (translate reads ``g.locale`` at
    # call time), so it must never be bound to a locale at import time.
    app.jinja_env.globals["_"] = lambda s, **kw: translate(s, **kw)

    @app.before_request
    def set_request_locale():
        # Display language for this request (app.i18n reads g.locale). Anonymous
        # users always get English — no browser detection. Static files skip the
        # work entirely; nothing template-rendered ever runs for them.
        if request.endpoint == "static":
            return
        if current_user.is_authenticated and current_user.language in SUPPORTED:
            g.locale = current_user.language
        else:
            g.locale = "en"

    @app.before_request
    def force_password_change():
        if (
            current_user.is_authenticated
            and current_user.must_change_password
            and request.endpoint not in PASSWORD_CHANGE_EXEMPT
        ):
            flash(_(FORCED_PASSWORD_CHANGE_MESSAGE), "warning")
            return redirect(url_for("main.profile_password"))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(error):
        # Bodies over MAX_CONTENT_LENGTH are rejected while the body is being
        # parsed — by CSRF (before_request) — before the route decorators run,
        # so the auth and forced-change gates must be reapplied here first.
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.must_change_password:
            flash(_(FORCED_PASSWORD_CHANGE_MESSAGE), "warning")
            return redirect(url_for("main.profile_password"))
        # Show the upload form error for avatar/logo uploads; other endpoints
        # keep werkzeug's default 413.
        if request.endpoint == "main.avatar_upload":
            return avatar_upload_error_response()
        if request.endpoint == "admin.branding":
            # The route's @role_required never runs (CSRF rejects the body in
            # before_request first), so the admin gate is reapplied here.
            # abort() is not an option inside an error handler — exceptions
            # raised from error handlers surface as 500s — so the 403 response
            # is returned directly, matching abort(403)'s output.
            if current_user.role != "admin":
                return Forbidden().get_response()
            return branding_upload_error_response()
        return error.get_response()

    return app
