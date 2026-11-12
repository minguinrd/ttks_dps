"""Backup core, admin routes, and scheduler wiring (see app/backup.py)."""

import sqlite3
from datetime import datetime, timedelta

from app import backup, create_app
from app.backup import create_backup, prune_backups


def _backup_dir(app, tmp_path):
    """Point BACKUP_DIR at a fresh (not yet existing) directory under tmp_path."""
    backup_dir = tmp_path / "backups"
    app.config["BACKUP_DIR"] = str(backup_dir)
    return backup_dir


def test_create_backup_produces_valid_sqlite(app, db_schema, tmp_path):
    backup_dir = _backup_dir(app, tmp_path)

    with app.app_context():
        path = create_backup()

    assert path.parent == backup_dir
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "users" in tables


def test_prune_keeps_newest_n(app, tmp_path):
    backup_dir = _backup_dir(app, tmp_path)
    backup_dir.mkdir()
    start = datetime(2026, 1, 1)
    names = []
    for i in range(9):
        name = f"ttks_dps-{start + timedelta(seconds=i):%Y%m%d-%H%M%S}.db"
        (backup_dir / name).touch()
        names.append(name)
    decoy = backup_dir / "ttks_dps.db"
    decoy.touch()

    with app.app_context():
        deleted = prune_backups(7)

    assert deleted == 2
    remaining = {p.name for p in backup_dir.glob("ttks_dps-*.db")}
    assert remaining == set(names[2:])
    assert decoy.exists()


def test_backup_now_creates_file(app, client, user_factory, login, tmp_path):
    backup_dir = _backup_dir(app, tmp_path)
    admin = user_factory(role="admin")
    login(client, admin)

    resp = client.post("/admin/backup/create")

    assert resp.status_code == 302
    files = list(backup_dir.glob("ttks_dps-*.db"))
    assert len(files) == 1

    # The listing page renders and shows the fresh file.
    page = client.get("/admin/backup")
    assert page.status_code == 200
    assert files[0].name in page.get_data(as_text=True)


def test_backup_requires_admin(client, user_factory, login):
    for role in ("agent", "user"):
        login(client, user_factory(role=role))

        assert client.get("/admin/backup").status_code == 403
        assert client.post("/admin/backup/create").status_code == 403


def test_download_returns_file(app, client, user_factory, login, tmp_path):
    _backup_dir(app, tmp_path)
    admin = user_factory(role="admin")
    with app.app_context():
        path = create_backup()
    login(client, admin)

    resp = client.get(f"/admin/backup/{path.name}/download")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["Content-Disposition"]


def test_download_path_traversal_rejected(client, user_factory, login):
    login(client, user_factory(role="admin"))

    assert client.get("/admin/backup/..%2Fttks_dps.db/download").status_code == 404
    assert client.get("/admin/backup/../ttks_dps.db/download").status_code == 404


def test_scheduler_not_started_in_testing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(backup, "start_scheduler", lambda application: calls.append(application))
    base = {
        "SECRET_KEY": "test",
        "DATA_DIR": str(tmp_path),
        "AVATAR_DIR": str(tmp_path / "avatars"),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/sched.db",
        "WTF_CSRF_ENABLED": False,
    }

    create_app({**base, "TESTING": True})
    assert calls == []

    created = create_app({**base, "TESTING": False})
    assert calls == [created]
