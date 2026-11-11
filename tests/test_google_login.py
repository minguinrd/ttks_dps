"""Google sign-in: env-gated button, OAuth callback, pending auto-create."""

from urllib.parse import parse_qs, urlparse

import pytest

from app import create_app
from app.extensions import db
from app.models import Notification, User

PENDING_MESSAGE = "Your account is awaiting admin approval."
SUSPENDED_MESSAGE = "This account has been suspended. Contact the administrator."
GOOGLE_FAILURE_MESSAGE = (
    "Google sign-in failed. Please try again or use your username and password."
)


@pytest.fixture()
def google_app(tmp_path):
    """Like the shared ``app`` fixture, but with Google OAuth configured.

    Points at the same ``test.db`` so rows seeded through ``user_factory``
    (which runs on the shared ``app``) are visible to the Google flow.
    """
    avatars = tmp_path / "avatars"
    avatars.mkdir(exist_ok=True)
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "WTF_CSRF_ENABLED": False,
            "AVATAR_DIR": str(avatars),
            "GOOGLE_CLIENT_ID": "test-client",
            "GOOGLE_CLIENT_SECRET": "test-secret",
        }
    )


def stub_google(monkeypatch, *, email, sub, name=None, email_verified=True):
    """Stub the Authlib token exchange to return a fixed Google userinfo."""
    from app.extensions import oauth

    userinfo = {
        "email": email,
        "sub": sub,
        "name": name,
        "email_verified": email_verified,
    }

    def _authorize_access_token(**kwargs):
        return {"userinfo": dict(userinfo)}

    monkeypatch.setattr(oauth.google, "authorize_access_token", _authorize_access_token)


def test_google_button_hidden_without_config(client):
    resp = client.get("/auth/login")

    assert resp.status_code == 200
    assert "Sign in with Google" not in resp.get_data(as_text=True)


def test_google_button_shown_with_config(google_app):
    client = google_app.test_client()

    resp = client.get("/auth/login")

    html = resp.get_data(as_text=True)
    assert "Sign in with Google" in html
    assert "/auth/google" in html


def test_google_login_redirects_to_google(google_app, monkeypatch):
    from app.extensions import oauth

    # Stub the OIDC discovery fetch at the Authlib client: the authorize URL
    # itself is built locally, no network I/O.
    monkeypatch.setattr(
        oauth.google,
        "load_server_metadata",
        lambda: {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"},
    )
    client = google_app.test_client()

    resp = client.get("/auth/google")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "accounts.google.com" in location
    query = parse_qs(urlparse(location).query)
    assert "/auth/google/callback" in query["redirect_uri"][0]


def test_google_redirect_failure_returns_generic_error(google_app, monkeypatch):
    from app.extensions import oauth

    # Discovery failure (e.g. Google unreachable): the route must fall back to
    # the generic message instead of raising a 500.
    def _discovery_boom(**kwargs):
        raise RuntimeError("OIDC discovery failed")

    monkeypatch.setattr(oauth.google, "load_server_metadata", _discovery_boom)
    client = google_app.test_client()

    resp = client.get("/auth/google")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login"
    page = client.get("/auth/login")
    assert GOOGLE_FAILURE_MESSAGE in page.get_data(as_text=True)


def test_google_new_email_creates_pending_user(app, google_app, db_schema, monkeypatch):
    stub_google(monkeypatch, email="New.Person@Example.com", sub="g-1", name="New Person")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/pending"
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="new.person@example.com"))
        assert user is not None
        assert user.status == "pending"
        assert user.role == "user"
        assert user.department_id is None
        assert user.google_sub == "g-1"
        assert user.username == "new.person"
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_pending_google_user_refused_on_login(app, google_app, user_factory, monkeypatch):
    user_factory(username="pendy", email="pendy@example.com", status="pending")
    stub_google(monkeypatch, email="pendy@example.com", sub="g-2")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback", follow_redirects=True)

    assert PENDING_MESSAGE in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_suspended_google_user_refused(app, google_app, user_factory, monkeypatch):
    user_factory(username="susy", email="susy@example.com", status="suspended")
    stub_google(monkeypatch, email="susy@example.com", sub="g-3")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback", follow_redirects=True)

    assert SUSPENDED_MESSAGE in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_existing_active_user_links_and_logs_in(app, google_app, user_factory, monkeypatch):
    user = user_factory(username="amy", email="amy@example.com", status="active")
    stub_google(monkeypatch, email="amy@example.com", sub="g-4")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == str(user.id)
    with app.app_context():
        stored = db.session.get(User, user.id)
        assert stored.google_sub == "g-4"


def test_sub_preferred_over_email(app, google_app, user_factory, monkeypatch):
    user = user_factory(username="linked", email="linked@example.com", google_sub="sub-A")
    stub_google(monkeypatch, email="someone-else@example.com", sub="sub-A")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == str(user.id)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 1


def test_unverified_email_rejected(app, google_app, db_schema, monkeypatch):
    stub_google(monkeypatch, email="eve@example.com", sub="g-5", email_verified=False)
    client = google_app.test_client()

    resp = client.get("/auth/google/callback", follow_redirects=True)

    assert GOOGLE_FAILURE_MESSAGE in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


def test_username_collision_gets_suffix(app, google_app, user_factory, monkeypatch):
    user_factory(username="dup", email="someone@example.com", status="active")
    stub_google(monkeypatch, email="dup@example.com", sub="g-6")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    with app.app_context():
        created = db.session.scalar(db.select(User).filter_by(google_sub="g-6"))
        assert created is not None
        assert created.username == "dup-2"
        assert created.status == "pending"


def test_state_mismatch_rejected(app, google_app, db_schema):
    client = google_app.test_client()

    resp = client.get("/auth/google/callback", follow_redirects=True)

    assert GOOGLE_FAILURE_MESSAGE in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_google_routes_without_config(client):
    for path in ("/auth/google", "/auth/google/callback"):
        resp = client.get(path)

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/auth/login"
        page = client.get("/auth/login")
        assert GOOGLE_FAILURE_MESSAGE in page.get_data(as_text=True)


def test_google_new_user_notifies_admins(app, google_app, user_factory, monkeypatch):
    admin = user_factory(username="g-admin", role="admin")
    user_factory(username="g-bystander")
    stub_google(monkeypatch, email="New.Person@Example.com", sub="g-7", name="New Person")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback")

    assert resp.status_code == 302
    # Same ping as self-registration: every admin, nobody else.
    with app.app_context():
        rows = db.session.scalars(db.select(Notification).order_by(Notification.id)).all()
        assert [row.user_id for row in rows] == [admin.id]
        assert rows[0].message == "New user new.person is awaiting approval."
        assert rows[0].url == "/admin/"
        assert rows[0].ticket_id is None
        assert rows[0].is_read is False


def test_pending_google_retry_does_not_notify_again(app, google_app, user_factory, monkeypatch):
    admin = user_factory(username="g-admin-retry", role="admin")
    stub_google(monkeypatch, email="re.retry@example.com", sub="g-8")
    client = google_app.test_client()

    client.get("/auth/google/callback")  # first sign-in creates the pending user
    with app.app_context():
        rows = db.session.scalars(db.select(Notification).filter_by(user_id=admin.id)).all()
        assert len(rows) == 1
        # Mark read first: notify() dedupes identical *unread* rows, so a read
        # row must not shield a regression that pings on every retry.
        for row in rows:
            row.is_read = True
        db.session.commit()

    client.get("/auth/google/callback")  # still-pending user retries Google

    with app.app_context():
        rows = db.session.scalars(db.select(Notification).filter_by(user_id=admin.id)).all()
        assert len(rows) == 1  # no additional notification


def test_google_sub_conflict_refused(app, google_app, user_factory, monkeypatch):
    user = user_factory(username="linky", email="linky@example.com", google_sub="sub-1")
    stub_google(monkeypatch, email="linky@example.com", sub="sub-2")
    client = google_app.test_client()

    resp = client.get("/auth/google/callback", follow_redirects=True)

    assert resp.status_code == 200
    assert GOOGLE_FAILURE_MESSAGE in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "_user_id" not in sess
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 1
        stored = db.session.get(User, user.id)
        assert stored.google_sub == "sub-1"
