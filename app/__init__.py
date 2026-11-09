import os

from flask import Flask

from app.config import Config
from app.extensions import csrf, db, login_manager, migrate


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

    return app
