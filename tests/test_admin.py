from datetime import datetime, timedelta, timezone

from app.admin.routes import compute_dashboard_stats
from app.extensions import db
from app.models import Department, User


def test_agent_forbidden_from_admin(client, user_factory, login):
    agent = user_factory(username="admin-nope", role="agent")
    login(client, agent)

    for path in ("/admin/", "/admin/users"):
        resp = client.get(path)

        assert resp.status_code == 403


def test_approve_pending_user(app, client, user_factory, login):
    admin = user_factory(username="admin-boss", role="admin")
    pending = user_factory(username="admin-pending", status="pending")
    login(client, admin)

    # The pending tab lists the awaiting user with its Approve/Reject actions.
    resp = client.get("/admin/users?status=pending")

    assert resp.status_code == 200
    assert "admin-pending" in resp.get_data(as_text=True)
    assert "Approve" in resp.get_data(as_text=True)

    resp = client.post(f"/admin/users/{pending.id}/approve")

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(User, pending.id)
        assert user.status == "active"

    # The approved user can now log in.
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "admin-pending", "password": "pass12345"})

    assert resp.status_code == 302


def test_reject_sets_suspended(app, client, user_factory, login):
    admin = user_factory(username="admin-rejector", role="admin")
    pending = user_factory(username="admin-rejectee", status="pending")
    login(client, admin)

    resp = client.post(f"/admin/users/{pending.id}/reject")

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(User, pending.id)
        assert user.status == "suspended"


def test_create_user_active_with_forced_password_change(app, client, user_factory, login):
    admin = user_factory(username="admin-creator", role="admin")
    login(client, admin)

    resp = client.get("/admin/users/new")

    assert resp.status_code == 200

    resp = client.post(
        "/admin/users/new",
        data={
            "username": "admin-made",
            "full_name": "Made By Admin",
            "email": "made@example.com",
            "role": "agent",
            "department": "",
            "initial_password": "first-one",
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username="admin-made"))
        assert user.status == "active"
        assert user.must_change_password is True
        assert user.role == "agent"
        assert user.check_password("first-one")

    # The initial password works, but the forced-change gate redirects first.
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "admin-made", "password": "first-one"})

    assert resp.status_code == 302
    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile/password"


def test_edit_user_role_department(app, client, user_factory, login):
    admin = user_factory(username="admin-editor", role="admin")
    with app.app_context():
        department = Department(name="Ops")
        db.session.add(department)
        db.session.commit()
        department_id = department.id
    target = user_factory(
        username="admin-target",
        role="user",
        full_name="Old Name",
        email="old@example.com",
    )
    login(client, admin)

    # The edit page renders prefilled (read-only username, reset-password form).
    resp = client.get(f"/admin/users/{target.id}/edit")

    assert resp.status_code == 200
    assert "admin-target" in resp.get_data(as_text=True)

    resp = client.post(
        f"/admin/users/{target.id}/edit",
        data={
            "username": "admin-target",
            "full_name": "New Name",
            "email": "new@example.com",
            "role": "agent",
            "department": str(department_id),
        },
    )

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(User, target.id)
        assert user.username == "admin-target"
        assert user.full_name == "New Name"
        assert user.email == "new@example.com"
        assert user.role == "agent"
        assert user.department_id == department_id


def test_suspend_and_reactivate(app, client, user_factory, login):
    admin = user_factory(username="admin-suspender", role="admin")
    victim = user_factory(username="admin-victim", role="user")
    login(client, admin)

    resp = client.post(f"/admin/users/{victim.id}/suspend")

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, victim.id).status == "suspended"

    # A suspended user cannot log in.
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "admin-victim", "password": "pass12345"})

    assert resp.status_code == 200
    assert "This account has been suspended." in resp.get_data(as_text=True)

    login(client, admin)
    resp = client.post(f"/admin/users/{victim.id}/reactivate")

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, victim.id).status == "active"


def test_reset_password_sets_flag_and_new_password_works(app, client, user_factory, login):
    admin = user_factory(username="admin-resetter", role="admin")
    victim = user_factory(username="admin-resetee", role="user")
    login(client, admin)

    resp = client.post(
        f"/admin/users/{victim.id}/reset-password",
        data={"new_password": "brand-new", "confirm": "brand-new"},
    )

    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(User, victim.id)
        assert user.must_change_password is True
        assert user.check_password("brand-new")
        assert not user.check_password("pass12345")

    # The new password logs in; the forced-change gate still applies.
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "admin-resetee", "password": "brand-new"})

    assert resp.status_code == 302


def test_department_crud(app, client, user_factory, login):
    admin = user_factory(username="admin-dept", role="admin")
    login(client, admin)

    resp = client.post("/admin/departments", data={"name": "IT Support"})

    assert resp.status_code == 302
    with app.app_context():
        department = db.session.scalar(db.select(Department).filter_by(name="IT Support"))
        assert department is not None
        department_id = department.id

    resp = client.get("/admin/departments")

    assert resp.status_code == 200
    assert "IT Support" in resp.get_data(as_text=True)

    resp = client.post(f"/admin/departments/{department_id}/delete")

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Department, department_id) is None


def test_delete_department_with_users_blocked(app, client, user_factory, login):
    admin = user_factory(username="admin-deptblock", role="admin")
    with app.app_context():
        department = Department(name="Sales")
        db.session.add(department)
        db.session.commit()
        department_id = department.id
    user_factory(username="admin-salesuser", department_id=department_id)
    login(client, admin)

    resp = client.post(f"/admin/departments/{department_id}/delete", follow_redirects=True)

    assert resp.status_code == 200
    assert "Cannot delete a department that still has users." in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Department, department_id) is not None


def test_compute_dashboard_stats(app, user_factory, ticket_factory):
    requester = user_factory(username="admin-stats-req")
    agent = user_factory(username="admin-stats-agent", role="agent")
    stale = user_factory(username="admin-stats-stale", role="agent", status="suspended")
    user_factory(username="admin-stats-pend1", status="pending")
    user_factory(username="admin-stats-pend2", status="pending")

    # SQLite hands back naive UTC datetimes; seed in the same shape.
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    ticket_factory(
        requester,
        category="hardware",
        priority="low",
        created_at=now - timedelta(days=3),
    )
    ticket_factory(
        requester,
        category="hardware",
        priority="low",
        created_at=now - timedelta(days=1),
    )
    ticket_factory(
        requester, category="software", priority="high", status="assigned", assignee=agent
    )
    ticket_factory(
        requester,
        category="software",
        priority="urgent",
        status="assigned",
        assignee=stale,
    )
    ticket_factory(
        requester,
        category="other",
        priority="normal",
        status="resolved",
        assignee=agent,
        resolved_at=now - timedelta(days=1),
    )
    ticket_factory(
        requester,
        category="other",
        priority="normal",
        status="resolved",
        assignee=agent,
        resolved_at=now - timedelta(days=8),
    )
    # "Unassigned" means no assignee regardless of ticket status, so this closed
    # ticket is the oldest unassigned one.
    ticket_factory(
        requester,
        category="network",
        priority="normal",
        status="closed",
        created_at=now - timedelta(days=10),
    )

    with app.app_context():
        stats = compute_dashboard_stats()

    assert stats == {
        "open": 2,
        "assigned": 2,
        "resolved_this_week": 1,
        "pending_users": 2,
        "by_category": {
            "hardware": 2,
            "software": 2,
            "network": 1,
            "access": 0,
            "other": 2,
        },
        "by_priority": {"low": 2, "normal": 3, "high": 1, "urgent": 1},
        "oldest_unassigned": now - timedelta(days=10),
        "stale_assignee": 1,
    }


def test_dashboard_renders(client, user_factory, login):
    admin = user_factory(username="admin-dashboard", role="admin")
    login(client, admin)

    resp = client.get("/admin/")

    assert resp.status_code == 200
