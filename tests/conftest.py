from uuid import uuid4

import pytest

from app import create_app
from app.extensions import db
from app.models import User


@pytest.fixture()
def app(tmp_path):
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "WTF_CSRF_ENABLED": False,
            "AVATAR_DIR": str(avatars),
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_schema(app):
    """Create the schema for one test and drop it afterwards."""
    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def user_factory(app, db_schema):
    """Return ``user_factory(role, status, password, **overrides) -> User`` (committed)."""

    def _factory(role="user", status="active", password="pass12345", **overrides):
        overrides.setdefault("username", f"user-{uuid4().hex[:8]}")
        with app.app_context():
            user = User(role=role, status=status, **overrides)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            # Hand back a detached, fully loaded instance usable outside app context.
            db.session.refresh(user)
            db.session.expunge(user)
            return user

    return _factory


@pytest.fixture()
def login():
    """Return ``login(client, user, password="pass12345") -> None`` (POSTs /auth/login)."""

    def _login(client, user, password="pass12345"):
        client.post("/auth/login", data={"username": user.username, "password": password})

    return _login
