from io import BytesIO
from pathlib import Path

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
