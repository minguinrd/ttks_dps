from app.extensions import db
from app.models import User


def test_seed_creates_admin_from_env(app, db_schema, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD", "sup3r-secret")

    result = app.test_cli_runner().invoke(args=["seed-admin"])

    assert result.exit_code == 0
    assert "created" in result.output
    with app.app_context():
        admins = db.session.scalars(db.select(User).where(User.role == "admin")).all()
        assert len(admins) == 1
        admin = admins[0]
        assert admin.username == "root"
        assert admin.status == "active"
        assert admin.must_change_password is True
        assert admin.check_password("sup3r-secret")


def test_seed_idempotent(app, db_schema, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD", "sup3r-secret")
    runner = app.test_cli_runner()

    first = runner.invoke(args=["seed-admin"])
    second = runner.invoke(args=["seed-admin"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "admin already exists" in second.output
    with app.app_context():
        count = db.session.scalar(db.select(db.func.count(User.id)).where(User.role == "admin"))
        assert count == 1


def test_seed_missing_env_fails(app, db_schema, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    result = app.test_cli_runner().invoke(args=["seed-admin"])

    assert result.exit_code == 1
    assert "ADMIN_PASSWORD" in result.output
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0
