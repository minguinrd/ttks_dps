import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app
from app.extensions import db
from app.models import User

PINNED_FLASH = "You must change your password before continuing."


def test_update_profile_fields(app, client, user_factory, login):
    user = user_factory(username="eddy")
    login(client, user)

    resp = client.post(
        "/profile",
        data={"full_name": "Ed D. Updated", "email": "eddy@example.com"},
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile"
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.full_name == "Ed D. Updated"
        assert row.email == "eddy@example.com"


def test_forced_password_change_gate(app, client, user_factory, login):
    user = user_factory(username="forcey", must_change_password=True)
    login(client, user)

    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile/password"
    with client.session_transaction() as sess:
        assert any(message == PINNED_FLASH for _category, message in sess.get("_flashes", []))

    resp = client.post("/auth/logout")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login"
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_change_password_requires_current(app, client, user_factory, login):
    user = user_factory(username="changer")
    login(client, user)
    old_hash = user.password_hash

    resp = client.post(
        "/profile/password",
        data={
            "current_password": "wrong-pass",
            "new_password": "brandnew1",
            "confirm": "brandnew1",
        },
    )

    assert resp.status_code == 200
    assert "Current password is incorrect." in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.password_hash == old_hash


def test_change_password_success_and_clears_flag(app, client, user_factory, login):
    user = user_factory(username="flagged", must_change_password=True)
    login(client, user)

    resp = client.post(
        "/profile/password",
        data={
            "current_password": "pass12345",
            "new_password": "brandnew1",
            "confirm": "brandnew1",
        },
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.must_change_password is False
        assert row.check_password("brandnew1") is True


def test_avatar_upload_valid(app, client, user_factory, login):
    user = user_factory(username="ava")
    login(client, user)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64

    resp = client.post(
        "/profile/avatar",
        data={"avatar": (BytesIO(png), "me.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile"
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.avatar_path is not None
        assert row.avatar_path.endswith(".png")
        avatar_path = row.avatar_path
    saved = list(Path(app.config["AVATAR_DIR"]).iterdir())
    assert len(saved) == 1
    assert saved[0].name == avatar_path
    assert saved[0].read_bytes() == png

    resp = client.get(f"/avatars/{user.id}")

    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_avatar_wrong_type_rejected(app, client, user_factory, login):
    user = user_factory(username="badtype")
    login(client, user)

    resp = client.post(
        "/profile/avatar",
        data={"avatar": (BytesIO(b"plain text"), "notes.txt", "text/plain")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    assert "Unsupported image type" in resp.get_data(as_text=True)
    assert list(Path(app.config["AVATAR_DIR"]).iterdir()) == []
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.avatar_path is None


def test_avatar_oversize_rejected(app, client, user_factory, login):
    user = user_factory(username="heavy")
    login(client, user)
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (3 * 1024 * 1024)

    resp = client.post(
        "/profile/avatar",
        data={"avatar": (BytesIO(big), "big.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    assert "File too large (max 2 MB)." in resp.get_data(as_text=True)
    assert list(Path(app.config["AVATAR_DIR"]).iterdir()) == []
    with app.app_context():
        row = db.session.get(User, user.id)
        assert row.avatar_path is None


def test_avatar_requires_login(client, user_factory):
    user = user_factory(username="ghost")

    resp = client.get(f"/avatars/{user.id}")

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login")


def test_avatar_404_when_missing(client, user_factory, login):
    user = user_factory(username="noavatar")
    login(client, user)

    resp = client.get(f"/avatars/{user.id}")

    assert resp.status_code == 404


def _csrf_token(html):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None, "csrf_token field not found"
    return match.group(1)


@pytest.fixture()
def csrf_app(tmp_path):
    """App with CSRF ENABLED (the production setting) plus one active user."""
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "WTF_CSRF_ENABLED": True,
            "AVATAR_DIR": str(avatars),
        }
    )
    with app.app_context():
        db.create_all()
        user = User(username="csrfy", status="active")
        user.set_password("pass12345")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    return SimpleNamespace(app=app, user_id=user_id, avatars=avatars)


@pytest.fixture()
def csrf_client(csrf_app):
    """Logged-in client on the CSRF-enabled app."""
    client = csrf_app.app.test_client()
    token = _csrf_token(client.get("/auth/login").get_data(as_text=True))
    resp = client.post(
        "/auth/login",
        data={"username": "csrfy", "password": "pass12345", "csrf_token": token},
    )
    assert resp.status_code == 302
    return SimpleNamespace(
        app=csrf_app.app, client=client, user_id=csrf_app.user_id, avatars=csrf_app.avatars
    )


def test_avatar_oversize_rejected_with_csrf_enabled(csrf_client):
    # Prove CSRF protection is genuinely enforced on this app (no token -> 400).
    resp = csrf_client.client.post("/profile", data={"full_name": "X", "email": "x@example.com"})
    assert resp.status_code == 400

    token = _csrf_token(csrf_client.client.get("/profile").get_data(as_text=True))
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (3 * 1024 * 1024)
    resp = csrf_client.client.post(
        "/profile/avatar",
        data={"csrf_token": token, "avatar": (BytesIO(big), "big.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    assert "File too large (max 2 MB)." in resp.get_data(as_text=True)
    assert list(csrf_client.avatars.iterdir()) == []
    with csrf_client.app.app_context():
        assert db.session.get(User, csrf_client.user_id).avatar_path is None


def test_avatar_oversize_anonymous_redirected_to_login(csrf_app):
    # The 413 handler fires before route decorators, so it must reapply the
    # login gate instead of rendering the profile page.
    client = csrf_app.app.test_client()
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (3 * 1024 * 1024)

    resp = client.post(
        "/profile/avatar",
        data={"avatar": (BytesIO(big), "big.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login")
    assert "File too large" not in resp.get_data(as_text=True)
    assert list(csrf_app.avatars.iterdir()) == []


def test_avatar_oversize_forced_change_redirected_to_password(csrf_app):
    # The 413 handler must also reapply the forced-change gate.
    with csrf_app.app.app_context():
        user = User(username="csrf-flagged", status="active", must_change_password=True)
        user.set_password("pass12345")
        db.session.add(user)
        db.session.commit()
    client = csrf_app.app.test_client()
    token = _csrf_token(client.get("/auth/login").get_data(as_text=True))
    resp = client.post(
        "/auth/login",
        data={"username": "csrf-flagged", "password": "pass12345", "csrf_token": token},
    )
    assert resp.status_code == 302

    big = b"\x89PNG\r\n\x1a\n" + b"x" * (3 * 1024 * 1024)
    resp = client.post(
        "/profile/avatar",
        data={"avatar": (BytesIO(big), "big.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile/password"
    with client.session_transaction() as sess:
        assert any(message == PINNED_FLASH for _category, message in sess.get("_flashes", []))
    assert list(csrf_app.avatars.iterdir()) == []
