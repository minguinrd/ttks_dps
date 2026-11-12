"""Restore CLI: integrity check, safety copy, database swap, and sidecar cleanup.

Fresh temp app like ``tests/test_migrations.py``: the schema comes from ``db
upgrade``, rows are seeded with raw SQL so the byte-level file copies the
restore flow works with can be asserted directly.
"""

import os
import shutil
import sqlite3
from pathlib import Path

from app import create_app
from app.extensions import db


def _fresh_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/live.db",
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": str(tmp_path),
            "AVATAR_DIR": str(tmp_path / "avatars"),
        }
    )


def _db_path(app) -> str:
    return app.config["SQLALCHEMY_DATABASE_URI"].removeprefix("sqlite:///")


def _schema(app) -> None:
    """Apply migrations, then drop the pooled engine connections.

    The app's connect listener turns on WAL journalling; an idle pooled
    connection would keep the WAL alive and leave later rows outside the main
    database file, which the restore flow's file copies would miss.
    """
    result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        db.engine.dispose()


def _add_user(db_file, username) -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, email,"
            " status, role, must_change_password)"
            " VALUES (?, 'x', ?, ?, 'active', 'user', 0)",
            (username, username, f"{username}@example.com"),
        )
        conn.commit()
    finally:
        conn.close()


def _users(db_file) -> list[str]:
    conn = sqlite3.connect(db_file)
    try:
        return [row[0] for row in conn.execute("SELECT username FROM users ORDER BY id")]
    finally:
        conn.close()


def _setup(tmp_path):
    """Fresh app whose backup.db holds only alice while live.db holds alice and bob."""
    app = _fresh_app(tmp_path)
    _schema(app)
    live = Path(_db_path(app))
    _add_user(live, "alice")
    backup_file = tmp_path / "backup.db"
    shutil.copy2(live, backup_file)
    _add_user(live, "bob")
    return app, live, backup_file


def test_restore_rejects_corrupt_file(tmp_path):
    app = _fresh_app(tmp_path)
    _schema(app)
    live = Path(_db_path(app))
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(os.urandom(512))
    before = live.read_bytes()

    result = app.test_cli_runner().invoke(args=["restore-backup", str(garbage)])

    assert result.exit_code == 1
    assert live.read_bytes() == before


def test_restore_replaces_database(tmp_path):
    app, live, backup_file = _setup(tmp_path)

    result = app.test_cli_runner().invoke(args=["restore-backup", str(backup_file)])

    assert result.exit_code == 0, result.output
    assert "Restart the service to apply the restored database." in result.output
    assert _users(live) == ["alice"]


def test_restore_takes_safety_copy(tmp_path):
    app, live, backup_file = _setup(tmp_path)

    result = app.test_cli_runner().invoke(args=["restore-backup", str(backup_file)])

    assert result.exit_code == 0, result.output
    safety_copies = list(tmp_path.glob("pre-restore-*.db"))
    assert len(safety_copies) == 1
    assert _users(safety_copies[0]) == ["alice", "bob"]


def test_restore_cleans_wal_sidecars(tmp_path):
    app = _fresh_app(tmp_path)
    _schema(app)
    live = Path(_db_path(app))
    backup_file = tmp_path / "backup.db"
    shutil.copy2(live, backup_file)
    wal = Path(f"{live}-wal")
    shm = Path(f"{live}-shm")
    wal.write_bytes(b"stale wal")
    shm.write_bytes(b"stale shm")

    result = app.test_cli_runner().invoke(args=["restore-backup", str(backup_file)])

    assert result.exit_code == 0, result.output
    assert not wal.exists()
    assert not shm.exists()


def test_restore_missing_file_fails(tmp_path):
    app = _fresh_app(tmp_path)
    _schema(app)

    result = app.test_cli_runner().invoke(args=["restore-backup", str(tmp_path / "nope.db")])

    assert result.exit_code == 1
