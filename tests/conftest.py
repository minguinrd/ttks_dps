import pytest

from app import create_app


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
