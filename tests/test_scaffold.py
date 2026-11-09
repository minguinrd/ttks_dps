from app.extensions import db


def test_create_app_boots_with_test_config(app):
    assert app.config["TESTING"] is True
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")


def test_sqlite_wal_enabled_on_connect(app):
    from sqlalchemy import text

    with app.app_context():
        mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"
