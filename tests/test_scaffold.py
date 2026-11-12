import importlib
from pathlib import Path

from sqlalchemy import text

import app as app_pkg
import app.config as app_config
from app.extensions import db


def test_create_app_boots_with_test_config(app):
    assert app.config["TESTING"] is True
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")


def test_sqlite_wal_enabled_on_connect(app):
    from sqlalchemy import text

    with app.app_context():
        mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"


def test_default_data_dir_is_absolute_and_connectable(monkeypatch, tmp_path):
    """Regression: a relative default DATA_DIR must resolve to one absolute place.

    Flask-SQLAlchemy resolves relative SQLite paths against app.instance_path,
    while the factory creates DATA_DIR relative to the cwd. Without absolute
    resolution the database parent is missing on first connection.
    """
    try:
        with monkeypatch.context() as m:
            m.chdir(tmp_path)
            m.delenv("DATA_DIR", raising=False)
            # This app is created without TESTING, so create_app would start the
            # real backup scheduler thread; keep the suite thread-free.
            m.setattr("app.backup.start_scheduler", lambda application: None)
            importlib.reload(app_config)
            importlib.reload(app_pkg)

            application = app_pkg.create_app()

            with application.app_context():
                db.session.execute(text("SELECT 1"))

            assert Path(application.config["DATA_DIR"]).is_absolute()
            assert (tmp_path / "data" / "ttks_dps.db").exists()
    finally:
        # restore the default Config for the remaining tests
        importlib.reload(app_config)
        importlib.reload(app_pkg)
