"""Security hardening, fail-fast configuration and operational endpoints."""

import os

import pytest

from app import backup, create_app


def _config(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATA_DIR": str(tmp_path),
        "AVATAR_DIR": str(tmp_path / "avatars"),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/hardening.db",
        "WTF_CSRF_ENABLED": False,
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize("hour", ["3", "24:00", "03:60", "aa:bb", ""])
def test_invalid_backup_hour_refuses_to_start(tmp_path, hour):
    with pytest.raises(ValueError, match="BACKUP_HOUR"):
        create_app(_config(tmp_path, BACKUP_HOUR=hour))


def test_manual_backup_failure_flashes_instead_of_500(
    app, client, user_factory, login, monkeypatch
):
    admin = user_factory(username="backup-fail-admin", role="admin")
    login(client, admin)

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr("app.admin.routes.run_backup_cycle", boom)

    resp = client.post("/admin/backup/create", follow_redirects=True)

    assert resp.status_code == 200
    assert "Backup failed." in resp.get_data(as_text=True)


def test_scheduler_lock_has_a_single_holder(tmp_path):
    lock = tmp_path / "backups" / ".scheduler.lock"
    first = backup._try_acquire_lock(lock)
    try:
        assert first is not None
        assert backup._try_acquire_lock(lock) is None
    finally:
        os.close(first)
    # Released with its holder: the next contender takes over.
    second = backup._try_acquire_lock(lock)
    assert second is not None
    os.close(second)
