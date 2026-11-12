"""Regression tests for SQLite batch migration behavior.

The app's connect listener forces ``PRAGMA foreign_keys=ON`` on every
connection, including Alembic's. Batch mode recreates ``users`` via
CREATE/copy/DROP/RENAME, and an FK-enforced ``DROP TABLE users`` fails
once tickets/comments/notifications reference it — leaving the
non-transactional ``_alembic_tmp_users`` behind and blocking every retry.
"""

import sqlite3

from app import create_app


def _fresh_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/migration.db",
            "WTF_CSRF_ENABLED": False,
            "AVATAR_DIR": str(tmp_path / "avatars"),
        }
    )


def _db_path(app) -> str:
    return app.config["SQLALCHEMY_DATABASE_URI"].removeprefix("sqlite:///")


def _upgrade(app, *args):
    return app.test_cli_runner().invoke(args=["db", "upgrade", *args])


def _seed_child_rows(db_path: str) -> None:
    """Insert a user plus a ticket referencing it (the FK child that blocks DROP).

    Raw SQL on purpose: the intermediate revision predates the google_sub
    column, so the current ORM model cannot write to it.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, password_hash, full_name, email,"
        " status, role, must_change_password)"
        " VALUES ('alice', 'x', 'Alice', 'alice@example.com',"
        " 'active', 'user', 0)"
    )
    user_id = conn.execute("SELECT id FROM users WHERE username = 'alice'").fetchone()[0]
    conn.execute(
        "INSERT INTO tickets (subject, description, category, priority,"
        " status, requester_id)"
        " VALUES ('Printer jam', 'Tray 2 keeps jamming.', 'hardware',"
        " 'normal', 'open', ?)",
        (user_id,),
    )
    conn.commit()
    conn.close()


def test_upgrade_with_child_rows(tmp_path):
    """Upgrading to the google_sub revision must work when child rows reference users."""
    app = _fresh_app(tmp_path)
    result = _upgrade(app, "751feed02aec")
    assert result.exit_code == 0, result.output
    _seed_child_rows(_db_path(app))

    # to head: add google_sub + settings + user language + notification keys + spanish default
    result = _upgrade(app)
    assert result.exit_code == 0, f"{result.output}{result.exception!r}"

    conn = sqlite3.connect(_db_path(app))
    cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    assert "google_sub" in cols
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    alice_row = conn.execute("SELECT language FROM users WHERE username='alice'").fetchone()
    assert alice_row[0] == "es"
    assert conn.execute("SELECT count(*) FROM tickets").fetchone()[0] == 1
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert version == "245bf1a60eae"
    conn.close()


def test_upgrade_recovers_from_leftover_temp_table(tmp_path):
    """A leftover _alembic_tmp_users from an interrupted run must not block the upgrade."""
    app = _fresh_app(tmp_path)
    result = _upgrade(app, "751feed02aec")
    assert result.exit_code == 0, result.output
    _seed_child_rows(_db_path(app))

    conn = sqlite3.connect(_db_path(app))
    conn.execute("CREATE TABLE _alembic_tmp_users (junk INTEGER)")
    conn.commit()
    conn.close()

    result = _upgrade(app)
    assert result.exit_code == 0, f"{result.output}{result.exception!r}"

    conn = sqlite3.connect(_db_path(app))
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "_alembic_tmp_users" not in tables
    cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    assert "google_sub" in cols
    conn.close()
