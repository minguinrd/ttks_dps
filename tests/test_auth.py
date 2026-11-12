from app.extensions import db
from app.models import User
from app.permissions import role_required


def test_register_creates_pending_user(client, app, db_schema):
    resp = client.post(
        "/auth/register",
        data={
            "username": "newbie",
            "password": "pass12345",
            "confirm": "pass12345",
            "full_name": "New Bee",
            "email": "newbie@example.com",
            "department": "",
        },
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/pending"
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username="newbie"))
        assert user is not None
        assert user.status == "pending"
        assert user.role == "user"


def test_pending_user_cannot_login(client, user_factory):
    user_factory(username="pendy", status="pending")

    resp = client.post("/auth/login", data={"username": "pendy", "password": "pass12345"})

    assert resp.status_code == 200
    assert "Tu cuenta está pendiente de aprobación del administrador." in resp.get_data(
        as_text=True
    )
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_suspended_login_refused(client, user_factory):
    user_factory(username="susy", status="suspended")

    resp = client.post("/auth/login", data={"username": "susy", "password": "pass12345"})

    assert resp.status_code == 200
    assert "Esta cuenta ha sido suspendida. Contacta con el administrador." in resp.get_data(
        as_text=True
    )
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_active_user_login_and_logout(client, user_factory):
    user = user_factory(username="active-amy")

    resp = client.post("/auth/login", data={"username": "active-amy", "password": "pass12345"})

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == str(user.id)

    resp = client.post("/auth/logout")

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_wrong_password_rejected(client, user_factory):
    user_factory(username="active-amy")

    resp = client.post("/auth/login", data={"username": "active-amy", "password": "wrong-pass"})

    assert resp.status_code == 200
    assert "Usuario o contraseña no válidos." in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_duplicate_username_rejected(client, app, user_factory):
    user_factory(username="dup")

    resp = client.post(
        "/auth/register",
        data={
            "username": "dup",
            "password": "pass12345",
            "confirm": "pass12345",
            "full_name": "Dup Li Kate",
            "email": "dup@example.com",
            "department": "",
        },
    )

    assert resp.status_code == 200
    assert "El nombre de usuario ya está en uso." in resp.get_data(as_text=True)
    with app.app_context():
        rows = db.session.scalars(db.select(User).filter_by(username="dup")).all()
        assert len(rows) == 1


def test_suspended_user_loses_existing_session(app, client, user_factory, login):
    victim = user_factory(username="revoke-victim")
    admin = user_factory(username="revoke-admin", role="admin")
    login(client, victim)

    resp = client.get("/tickets/mine")

    assert resp.status_code == 200

    # An admin suspends the user while their session cookie is still alive.
    admin_client = app.test_client()
    login(admin_client, admin)
    resp = admin_client.post(f"/admin/users/{victim.id}/suspend")

    assert resp.status_code == 302

    resp = client.get("/tickets/mine")

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login")


def test_role_required_forbids_other_roles(app, client, user_factory, login):
    @app.get("/admin-only")
    @role_required("admin")
    def admin_only():
        return "secret"

    user = user_factory(username="plain", role="user")
    login(client, user)

    resp = client.get("/admin-only")

    assert resp.status_code == 403


def test_root_redirects_by_role(client, user_factory, login):
    user = user_factory(username="u1", role="user")
    login(client, user)

    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/tickets/mine"

    client.post("/auth/logout")
    agent = user_factory(username="a1", role="agent")
    login(client, agent)

    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/tickets/queue"
