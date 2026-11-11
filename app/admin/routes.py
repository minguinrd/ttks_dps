from datetime import datetime, timedelta, timezone

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin import admin_bp
from app.admin.forms import AdminUserForm, DepartmentForm, ResetPasswordForm
from app.extensions import db
from app.models import Category, Department, Priority, Role, Ticket, TicketStatus, User
from app.permissions import role_required


def compute_dashboard_stats() -> dict:
    """Aggregate the dashboard numbers (reads the DB; needs an app context).

    Keys: ``open``/``assigned`` count tickets by status; ``resolved_this_week``
    counts tickets resolved in the last 7 days; ``pending_users`` counts awaiting
    registrations; ``by_category``/``by_priority`` are zero-filled breakdowns over
    all tickets; ``oldest_unassigned`` is the ``created_at`` of the oldest ticket
    with no assignee (or ``None``); ``stale_assignee`` counts tickets whose
    assignee is not an active user.
    """
    # SQLite stores naive UTC datetimes; keep cutoffs in the same shape.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    week_ago = now - timedelta(days=7)

    def breakdown(column, values):
        counts = {value: 0 for value in values}
        for value, count in db.session.execute(
            db.select(column, db.func.count(Ticket.id)).group_by(column)
        ):
            counts[value] = count
        return counts

    return {
        "open": db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(Ticket.status == TicketStatus.open)
        ),
        "assigned": db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(Ticket.status == TicketStatus.assigned)
        ),
        "resolved_this_week": db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(Ticket.resolved_at >= week_ago)
        ),
        "pending_users": db.session.scalar(
            db.select(db.func.count(User.id)).where(User.status == "pending")
        ),
        "by_category": breakdown(Ticket.category, [item.value for item in Category]),
        "by_priority": breakdown(Ticket.priority, [item.value for item in Priority]),
        "oldest_unassigned": db.session.scalar(
            db.select(db.func.min(Ticket.created_at)).where(Ticket.assignee_id.is_(None))
        ),
        "stale_assignee": db.session.scalar(
            db.select(db.func.count(Ticket.id))
            .join(User, Ticket.assignee_id == User.id)
            .where(User.status != "active")
        ),
    }


@admin_bp.route("/")
@login_required
@role_required("admin")
def dashboard():
    return render_template("admin/dashboard.html", stats=compute_dashboard_stats())


@admin_bp.route("/users")
@login_required
@role_required("admin")
def users():
    # Tabs narrow the list via ?status=; anything else shows everyone.
    status = request.args.get("status", "all")
    if status not in ("pending", "active", "suspended", "all"):
        status = "all"
    query = db.select(User).order_by(User.username)
    if status != "all":
        query = query.where(User.status == status)
    return render_template("admin/users.html", users=db.session.scalars(query).all(), status=status)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def user_new():
    form = AdminUserForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            full_name=form.full_name.data,
            email=form.email.data,
            department_id=int(form.department.data) if form.department.data else None,
            role=form.role.data,
            # Creating the account is the approval: it starts active and the
            # admin-set password is temporary.
            status="active",
            must_change_password=True,
        )
        user.set_password(form.initial_password.data)
        db.session.add(user)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, user=None, reset_form=None)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def user_edit(user_id):
    user = _user_or_404(user_id)
    form = AdminUserForm(edit_user=user)
    if form.validate_on_submit():
        # An admin must never demote themselves: as the sole admin that would
        # lock administration out permanently. Name/email self-edits stay fine.
        if user.id == current_user.id and form.role.data != Role.admin:
            flash("You cannot change your own role.", "danger")
            return redirect(url_for("admin.users"))
        # The username is fixed; editing covers name, email, role, department.
        user.full_name = form.full_name.data
        user.email = form.email.data
        user.role = form.role.data
        user.department_id = int(form.department.data) if form.department.data else None
        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))
    if not form.is_submitted():
        _prefill_user_form(form, user)
    return render_template(
        "admin/user_form.html", form=form, user=user, reset_form=ResetPasswordForm()
    )


@admin_bp.route("/users/<int:user_id>/approve", methods=["POST"])
@login_required
@role_required("admin")
def user_approve(user_id):
    return _set_status(user_id, "active", "User approved.")


@admin_bp.route("/users/<int:user_id>/reject", methods=["POST"])
@login_required
@role_required("admin")
def user_reject(user_id):
    return _set_status(user_id, "suspended", "User rejected.")


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@role_required("admin")
def user_suspend(user_id):
    # Suspending your own account would lock administration out permanently.
    if user_id == current_user.id:
        flash("You cannot suspend your own account.", "danger")
        return redirect(url_for("admin.users"))
    return _set_status(user_id, "suspended", "User suspended.")


@admin_bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@login_required
@role_required("admin")
def user_reactivate(user_id):
    return _set_status(user_id, "active", "User reactivated.")


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@role_required("admin")
def user_reset_password(user_id):
    user = _user_or_404(user_id)
    form = ResetPasswordForm()
    if form.validate_on_submit():
        # The new password is temporary: the forced-change gate still applies.
        user.set_password(form.new_password.data)
        user.must_change_password = True
        db.session.commit()
        flash("Password reset.", "success")
        return redirect(url_for("admin.user_edit", user_id=user.id))
    profile_form = AdminUserForm(formdata=None, edit_user=user)
    _prefill_user_form(profile_form, user)
    return render_template("admin/user_form.html", form=profile_form, user=user, reset_form=form)


@admin_bp.route("/departments", methods=["GET", "POST"])
@login_required
@role_required("admin")
def departments():
    form = DepartmentForm()
    if form.validate_on_submit():
        db.session.add(Department(name=form.name.data))
        db.session.commit()
        flash("Department created.", "success")
        return redirect(url_for("admin.departments"))
    return render_template(
        "admin/departments.html",
        form=form,
        departments=db.session.scalars(db.select(Department).order_by(Department.name)).all(),
    )


@admin_bp.route("/departments/<int:department_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def department_delete(department_id):
    department = db.session.get(Department, department_id)
    if department is None:
        abort(404)
    if department.users:
        flash("Cannot delete a department that still has users.", "danger")
        return redirect(url_for("admin.departments"))
    # Tickets also hold a foreign key to the department (enforced by SQLite).
    ticket_count = db.session.scalar(
        db.select(db.func.count(Ticket.id)).where(Ticket.department_id == department.id)
    )
    if ticket_count:
        flash("Cannot delete a department that still has tickets.", "danger")
        return redirect(url_for("admin.departments"))
    db.session.delete(department)
    db.session.commit()
    flash("Department deleted.", "success")
    return redirect(url_for("admin.departments"))


@admin_bp.route("/departments/<int:department_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def department_edit(department_id):
    department = db.session.get(Department, department_id)
    if department is None:
        abort(404)
    form = DepartmentForm(edit_department=department)
    if form.validate_on_submit():
        department.name = form.name.data
        db.session.commit()
        flash("Department updated.", "success")
        return redirect(url_for("admin.departments"))
    if not form.is_submitted():
        form.name.data = department.name
    return render_template("admin/department_edit.html", form=form, department=department)


def _user_or_404(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    return user


def _set_status(user_id: int, status: str, message: str):
    """Shared body of approve/reject/suspend/reactivate: set the status and flash."""
    user = _user_or_404(user_id)
    user.status = status
    db.session.commit()
    flash(message, "success")
    return redirect(url_for("admin.users"))


def _prefill_user_form(form: AdminUserForm, user: User) -> None:
    """Fill the edit form from ``user`` (only used when rendering, never after a POST)."""
    form.username.data = user.username
    form.full_name.data = user.full_name
    form.email.data = user.email
    form.role.data = user.role
    form.department.data = str(user.department_id) if user.department_id else ""
