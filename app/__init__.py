import os

from flask import Flask, flash, redirect, request, url_for
from flask_login import current_user

from app import models  # noqa: F401  # register ORM mappers so Flask-Migrate can autogenerate
from app.auth import auth_bp
from app.config import Config
from app.extensions import csrf, db, login_manager, migrate
from app.main import main_bp

# Endpoints a user with a pending forced password change may still reach.
PASSWORD_CHANGE_EXEMPT = {"static", "auth.logout", "main.profile_password"}


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

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.before_request
    def force_password_change():
        if (
            current_user.is_authenticated
            and current_user.must_change_password
            and request.endpoint not in PASSWORD_CHANGE_EXEMPT
        ):
            flash("You must change your password before continuing.", "warning")
            return redirect(url_for("main.profile_password"))

    return app
