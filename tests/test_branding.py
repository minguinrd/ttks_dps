"""Branding settings: site name, accent color, and logo state."""

import re
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.branding import get_branding, get_setting, set_setting
from app.extensions import db
from app.models import User


def test_settings_defaults_without_rows(app, db_schema):
    with app.app_context():
        branding = get_branding()
    assert branding["site_name"] == "Tech Support"
    assert branding["accent_color"] == "#0d6efd"
    assert branding["has_logo"] is False


def test_branding_context_reflects_settings(app, db_schema, client):
    with app.app_context():
        set_setting("site_name", "Acme IT")
    html = client.get("/auth/login").get_data(as_text=True)
    assert re.search(r"<title>[^<]*Acme IT[^<]*</title>", html)
    assert re.search(r'<a class="navbar-brand"[^>]*>\s*Acme IT\s*</a\s*>', html)


def test_accent_color_css_var_rendered(app, db_schema, client):
    with app.app_context():
        set_setting("accent_color", "#123456")
    html = client.get("/auth/login").get_data(as_text=True)
    assert "--brand-accent: #123456" in html


def test_accent_color_sanitized_on_render(app, db_schema, client):
    with app.app_context():
        set_setting("accent_color", "#fff;</style><script>alert(1)</script>")
    html = client.get("/auth/login").get_data(as_text=True)
    assert "#0d6efd" in html
    assert "<script>alert(1)</script>" not in html


def test_branding_db_error_not_silent(app, db_schema, monkeypatch):
    """Only the missing-``settings``-table case degrades to defaults.

    Any other OperationalError — lock, I/O, or ``no such table`` for a
    DIFFERENT table name — must propagate instead of being silently swallowed
    as "default branding".
    """

    def raise_operational(message):
        def _get(*args, **kwargs):
            raise OperationalError(message, None, Exception(message))

        return _get

    def raise_no_such_table(table):
        message = f"no such table: {table}"

        def _get(*args, **kwargs):
            raise OperationalError(message, None, None)

        return _get

    def raise_operational_raw(statement, orig):
        def _get(*args, **kwargs):
            raise OperationalError(statement, None, orig)

        return _get

    with app.app_context():
        monkeypatch.setattr(db.session, "get", raise_operational("no such table: settings"))
        assert get_branding() == {
            "site_name": "Tech Support",
            "accent_color": "#0d6efd",
            "has_logo": False,
            "logo_url": None,
        }

        monkeypatch.setattr(db.session, "get", raise_operational("database is locked"))
        with pytest.raises(OperationalError, match="database is locked"):
            get_branding()

        # A missing DIFFERENT table must propagate: the name must match exactly.
        monkeypatch.setattr(db.session, "get", raise_no_such_table("settings-archive"))
        with pytest.raises(OperationalError, match="no such table: settings-archive"):
            get_branding()
        monkeypatch.setattr(db.session, "get", raise_no_such_table("settings archive"))
        with pytest.raises(OperationalError, match="no such table: settings archive"):
            get_branding()

        # SQL text is not an error message: the statement must never be searched,
        # so a comment like ``-- no such table: settings`` cannot swallow the
        # error (nor can such wording smuggled anywhere outside the DBAPI
        # orig message).
        monkeypatch.setattr(
            db.session,
            "get",
            raise_operational_raw("SELECT 1 -- no such table: settings", None),
        )
        with pytest.raises(OperationalError):
            get_branding()
        monkeypatch.setattr(
            db.session,
            "get",
            raise_operational_raw("boom", "SELECT 1 -- no such table: settings"),
        )
        with pytest.raises(OperationalError):
            get_branding()


def test_active_nav_link_rule_present(app, db_schema, client):
    """The active-nav-link accent rule must out-specific Bootstrap's own
    ``.navbar-nav .nav-link.active`` rule."""
    html = client.get("/auth/login").get_data(as_text=True)
    assert re.search(
        r"\.navbar\s+\.navbar-nav\s+\.nav-link\.active\s*\{[^}]*var\(--brand-accent\)", html
    )


def test_branding_requires_admin(app, db_schema, client, user_factory, login):
    user = user_factory(role="user")
    login(client, user)

    assert client.get("/admin/branding").status_code == 403
    assert client.post("/admin/branding", data={"site_name": "X"}).status_code == 403
    # The nav link is gated to admins, like Admin and Backup.
    assert 'href="/admin/branding"' not in client.get("/auth/login").get_data(as_text=True)

    anon = app.test_client()
    for resp in (
        anon.get("/admin/branding"),
        anon.post("/admin/branding", data={"site_name": "X"}),
    ):
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/auth/login")
    assert 'href="/admin/branding"' not in anon.get("/auth/login").get_data(as_text=True)


def test_branding_save_updates_site_name_and_color(app, db_schema, client, user_factory, login):
    admin = user_factory(role="admin")
    login(client, admin)
    client.get("/admin/branding")  # fetch the form first (carries the CSRF token in production)

    resp = client.post("/admin/branding", data={"site_name": "Acme IT", "accent_color": "#123456"})

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/branding"
    with app.app_context():
        assert get_setting("site_name") == "Acme IT"
        assert get_setting("accent_color") == "#123456"
    html = client.get("/admin/branding").get_data(as_text=True)
    assert "Branding updated." in html
    assert 'value="Acme IT"' in html
    assert 'value="#123456"' in html
    assert 'href="/admin/branding"' in html


def test_branding_invalid_color_rejected(app, db_schema, client, user_factory, login):
    admin = user_factory(role="admin")
    login(client, admin)
    with app.app_context():
        set_setting("site_name", "Original")
        set_setting("accent_color", "#222222")
    client.get("/admin/branding")

    resp = client.post("/admin/branding", data={"site_name": "Changed", "accent_color": "red"})

    assert resp.status_code == 200
    assert "Use a hex color like #123456." in resp.get_data(as_text=True)
    with app.app_context():
        assert get_setting("site_name") == "Original"
        assert get_setting("accent_color") == "#222222"


def test_logo_upload_served_publicly(app, db_schema, client, user_factory, login, tmp_path):
    app.config["DATA_DIR"] = str(tmp_path)  # branding files land in a per-test dir
    admin = user_factory(role="admin")
    login(client, admin)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    client.get("/admin/branding")

    resp = client.post(
        "/admin/branding",
        data={
            "site_name": "Acme IT",
            "accent_color": "#123456",
            "logo": (BytesIO(png), "logo.png", "image/png"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    with app.app_context():
        assert get_setting("logo_file") == "logo.png"
    assert (tmp_path / "branding" / "logo.png").read_bytes() == png

    anon = app.test_client()
    resp = anon.get("/branding/logo")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("image/")
    html = anon.get("/auth/login").get_data(as_text=True)
    assert '<img src="/branding/logo"' in html


def test_logo_upload_rejects_bad_type(app, db_schema, client, user_factory, login, tmp_path):
    app.config["DATA_DIR"] = str(tmp_path)
    admin = user_factory(role="admin")
    login(client, admin)
    client.get("/admin/branding")
    too_big = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024 + 1)
    cases = [
        ((BytesIO(b"\x89PNG\r\n\x1a\n"), "evil.php", "image/png"), "Unsupported image type"),
        ((BytesIO(b"\x89PNG\r\n\x1a\n"), "../../evil.php", "image/png"), "Unsupported image type"),
        ((BytesIO(too_big), "big.png", "image/png"), "File too large"),
    ]
    for upload, error in cases:
        resp = client.post(
            "/admin/branding",
            data={"site_name": "Acme IT", "accent_color": "#123456", "logo": upload},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert error in resp.get_data(as_text=True)
        branding_dir = tmp_path / "branding"
        assert not branding_dir.exists() or list(branding_dir.iterdir()) == []
        with app.app_context():
            assert get_setting("logo_file") is None


def test_logo_remove_reverts_to_text_brand(app, db_schema, client, user_factory, login, tmp_path):
    app.config["DATA_DIR"] = str(tmp_path)
    admin = user_factory(role="admin")
    login(client, admin)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    client.post(
        "/admin/branding",
        data={
            "site_name": "Acme IT",
            "accent_color": "#123456",
            "logo": (BytesIO(png), "logo.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    logo_path = tmp_path / "branding" / "logo.png"
    assert logo_path.exists()

    resp = client.post("/admin/branding/logo/delete")

    assert resp.status_code == 302
    assert not logo_path.exists()
    with app.app_context():
        assert get_setting("logo_file") is None
        assert get_branding()["has_logo"] is False
    html = app.test_client().get("/auth/login").get_data(as_text=True)
    assert re.search(r'<a class="navbar-brand"[^>]*>\s*Acme IT\s*</a\s*>', html)


def _csrf_token(html):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match is not None, "csrf_token field not found"
    return match.group(1)


def _csrf_session(tmp_path, role):
    """CSRF-enabled app (the production setting) with a logged-in ``role`` user.

    Mirrors ``tests.test_profile``'s ``csrf_app``/``csrf_client`` so the
    oversize-upload path through the app-level 413 handler is exercised for
    real: CSRF's ``before_request`` rejects the body before any route runs.
    """
    (tmp_path / "avatars").mkdir()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "WTF_CSRF_ENABLED": True,
            "AVATAR_DIR": str(tmp_path / "avatars"),
            "DATA_DIR": str(tmp_path),
        }
    )
    with app.app_context():
        db.create_all()
        admin = User(username=f"brand-{role}", role=role, status="active")
        admin.set_password("pass12345")
        db.session.add(admin)
        db.session.commit()
    client = app.test_client()
    token = _csrf_token(client.get("/auth/login").get_data(as_text=True))
    resp = client.post(
        "/auth/login",
        data={"username": f"brand-{role}", "password": "pass12345", "csrf_token": token},
    )
    assert resp.status_code == 302
    return SimpleNamespace(app=app, client=client, data_dir=tmp_path)


@pytest.fixture()
def csrf_admin(tmp_path):
    return _csrf_session(tmp_path, "admin")


@pytest.fixture()
def csrf_regular_user(tmp_path):
    return _csrf_session(tmp_path, "user")


def test_logo_oversize_rejected_with_csrf_enabled(csrf_admin):
    # Prove CSRF protection is genuinely enforced on this app (no token -> 400).
    resp = csrf_admin.client.post(
        "/admin/branding", data={"site_name": "X", "accent_color": "#123456"}
    )
    assert resp.status_code == 400

    token = _csrf_token(csrf_admin.client.get("/admin/branding").get_data(as_text=True))
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024 + 1)
    resp = csrf_admin.client.post(
        "/admin/branding",
        data={
            "csrf_token": token,
            "site_name": "Acme IT",
            "accent_color": "#123456",
            "logo": (BytesIO(big), "big.png", "image/png"),
        },
        content_type="multipart/form-data",
    )

    # The body is rejected during CSRF's before_request — before the route ever
    # runs — so the app-level 413 handler must render the branding form with
    # the inline size error instead of werkzeug's generic 413, and no partial
    # branding state may be written.
    assert resp.status_code == 200
    assert "Archivo demasiado grande (máx. 2 MB)." in resp.get_data(as_text=True)
    branding_dir = csrf_admin.data_dir / "branding"
    assert not branding_dir.exists() or list(branding_dir.iterdir()) == []
    with csrf_admin.app.app_context():
        assert get_setting("logo_file") is None
        assert get_setting("site_name") is None


def test_branding_oversize_post_rejects_non_admin(csrf_regular_user):
    # CSRF's before_request rejects the oversized body before the route's
    # @role_required ever runs, so the app-level 413 handler must apply the
    # admin gate itself: a non-admin must never see the branding form.
    token = _csrf_token(csrf_regular_user.client.get("/notifications").get_data(as_text=True))
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024 + 1)
    resp = csrf_regular_user.client.post(
        "/admin/branding",
        data={
            "csrf_token": token,
            "site_name": "Acme IT",
            "accent_color": "#123456",
            "logo": (BytesIO(big), "big.png", "image/png"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 403
