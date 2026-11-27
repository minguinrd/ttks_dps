import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from app.admin import admin_bp
from app.admin.forms import (
    AdminUserForm,
    BrandingForm,
    CategoryForm,
    DepartmentForm,
    ResetPasswordForm,
)
from app.backup import run_backup_cycle
from app.branding import get_branding, get_setting, set_setting
from app.durations import format_duration
from app.extensions import db
from app.i18n import _
from app.main.routes import branding_upload_error_response
from app.models import Category, Department, Priority, Role, Setting, Ticket, TicketStatus, User
from app.permissions import role_required
from app.search import LIKE_ESCAPE, like_pattern


def compute_dashboard_stats() -> dict:
    """Aggregate the dashboard numbers (reads the DB; needs an app context).

    Keys: ``open``/``assigned`` count tickets by status; ``resolved_this_week``
    counts tickets resolved in the last 7 days; ``pending_users`` counts awaiting
    registrations; ``by_category``/``by_priority`` are zero-filled breakdowns over
    all tickets; ``oldest_unassigned`` is the ``created_at`` of the oldest open
    ticket with no assignee (or ``None``); ``stale_assignee`` counts in-progress
    tickets whose assignee is not an active user.
    """
    # SQLite stores naive UTC datetimes; keep cutoffs in the same shape.
    now = _naive_utc_now()
    week_ago = now - timedelta(days=7)

    def breakdown(column, values):
        counts = dict.fromkeys(values, 0)
        for value, count in db.session.execute(
            db.select(column, db.func.count(Ticket.id)).group_by(column)
        ):
            counts[value] = count
        return counts

    categories = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    category_counts = breakdown(Ticket.category_id, [category.id for category in categories])

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
        "by_category": {category.name: category_counts[category.id] for category in categories},
        "by_priority": breakdown(Ticket.priority, [item.value for item in Priority]),
        # Only tickets still waiting in the queue need someone to pick them up.
        "oldest_unassigned": db.session.scalar(
            db.select(db.func.min(Ticket.created_at)).where(
                Ticket.status == TicketStatus.open, Ticket.assignee_id.is_(None)
            )
        ),
        "stale_assignee": db.session.scalar(_stale_query(db.func.count(Ticket.id))),
    }


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _stale_query(*columns):
    """In-progress tickets held by an assignee who can no longer log in."""
    return (
        db.select(*columns)
        .join(User, Ticket.assignee_id == User.id)
        .where(Ticket.status == TicketStatus.assigned, User.status != "active")
    )


def _backup_files() -> list[Path]:
    """Backup files in BACKUP_DIR, newest first (names sort chronologically)."""
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    return sorted(backup_dir.glob("ttks_dps-*.db"), reverse=True)


# A daily schedule plus a couple of hours' slack before the dashboard warns.
BACKUP_STALE_AFTER = timedelta(hours=26)


def compute_dashboard_details() -> dict:
    """The lists behind the dashboard figures: what to act on and who is busy."""
    now = _naive_utc_now()
    week_ago = now - timedelta(days=7)

    oldest_open = db.session.scalar(
        Ticket.list_query()
        .where(Ticket.status == TicketStatus.open, Ticket.assignee_id.is_(None))
        .order_by(Ticket.created_at)
        .limit(1)
    )
    pending_users = db.session.scalars(
        db.select(User).where(User.status == "pending").order_by(User.created_at).limit(5)
    ).all()
    stale_tickets = db.session.scalars(
        _stale_query(Ticket)
        .options(selectinload(Ticket.assignee))
        .order_by(Ticket.created_at)
        .limit(5)
    ).all()
    urgent_pending = db.session.scalar(
        db.select(db.func.count(Ticket.id)).where(
            Ticket.priority == Priority.urgent,
            Ticket.status.in_((TicketStatus.open, TicketStatus.assigned)),
        )
    )

    # Workload: every active agent/admin, even with nothing on their plate.
    in_progress = dict(
        db.session.execute(
            db.select(Ticket.assignee_id, db.func.count(Ticket.id))
            .where(Ticket.status == TicketStatus.assigned)
            .group_by(Ticket.assignee_id)
        ).all()
    )
    resolved_week = dict(
        db.session.execute(
            db.select(Ticket.assignee_id, db.func.count(Ticket.id))
            .where(Ticket.resolved_at >= week_ago)
            .group_by(Ticket.assignee_id)
        ).all()
    )
    staff = db.session.scalars(
        db.select(User).where(User.role.in_((Role.agent, Role.admin)), User.status == "active")
    ).all()
    workload = sorted(
        (
            {
                "user": member,
                "in_progress": in_progress.get(member.id, 0),
                "resolved_week": resolved_week.get(member.id, 0),
            }
            for member in staff
        ),
        key=lambda row: (-row["in_progress"], -row["resolved_week"], row["user"].username),
    )

    users_by_role = dict.fromkeys((Role.user.value, Role.agent.value, Role.admin.value), 0)
    for role, count in db.session.execute(
        db.select(User.role, db.func.count(User.id))
        .where(User.status == "active")
        .group_by(User.role)
    ):
        users_by_role[role] = count
    suspended_users = db.session.scalar(
        db.select(db.func.count(User.id)).where(User.status == "suspended")
    )

    backups = _backup_files()
    last_backup = None
    if backups:
        stat = backups[0].stat()
        taken = datetime.fromtimestamp(stat.st_mtime, UTC).replace(tzinfo=None)
        last_backup = {
            "name": backups[0].name,
            "taken": taken,
            "age": now - taken,
            "size": stat.st_size,
        }

    recent = db.session.scalars(
        Ticket.list_query().order_by(Ticket.created_at.desc()).limit(6)
    ).all()

    return {
        "now": now,
        "oldest_open": oldest_open,
        "oldest_open_age": (now - oldest_open.created_at) if oldest_open else None,
        "pending_user_list": pending_users,
        "stale_tickets": stale_tickets,
        "urgent_pending": urgent_pending,
        "workload": workload,
        "workload_max": max([1, *(row["in_progress"] for row in workload)]),
        "users_by_role": users_by_role,
        "suspended_users": suspended_users,
        "last_backup": last_backup,
        "backup_stale": last_backup is None or last_backup["age"] > BACKUP_STALE_AFTER,
        "backup_count": len(backups),
        "backup_hour": current_app.config["BACKUP_HOUR"],
        "categories_count": db.session.scalar(db.select(db.func.count(Category.id))),
        "departments_count": db.session.scalar(db.select(db.func.count(Department.id))),
        "google_enabled": bool(
            current_app.config.get("GOOGLE_CLIENT_ID")
            and current_app.config.get("GOOGLE_CLIENT_SECRET")
        ),
        "recent": recent,
    }


@admin_bp.route("/")
@login_required
@role_required("admin")
def dashboard():
    return render_template(
        "admin/dashboard.html",
        stats=compute_dashboard_stats(),
        details=compute_dashboard_details(),
        duration=format_duration,
    )


@admin_bp.route("/users")
@login_required
@role_required("admin")
def users():
    # Tabs narrow the list via ?status=; anything else shows everyone. The
    # search box (?q=) and role filter combine with the tab, and the tab
    # counts honour them.
    status = request.args.get("status", "all")
    if status not in ("pending", "active", "suspended", "all"):
        status = "all"
    role = request.args.get("role", "")
    if role not in {item.value for item in Role}:
        role = ""
    search = request.args.get("q", "").strip()[:100]

    filters = []
    if role:
        filters.append(User.role == role)
    if search:
        pattern = like_pattern(search)
        filters.append(
            db.or_(
                User.username.ilike(pattern, escape=LIKE_ESCAPE),
                User.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                User.email.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    counts = dict.fromkeys(("pending", "active", "suspended"), 0)
    for value, count in db.session.execute(
        db.select(User.status, db.func.count(User.id)).where(*filters).group_by(User.status)
    ):
        counts[value] = count
    counts["all"] = sum(counts.values())

    query = (
        db.select(User)
        .options(selectinload(User.department))
        .where(*filters)
        .order_by(User.username)
    )
    if status != "all":
        query = query.where(User.status == status)
    return render_template(
        "admin/users.html",
        users=db.session.scalars(query).all(),
        status=status,
        role=role,
        search=search,
        counts=counts,
    )


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
        flash(_("User created."), "success")
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
            flash(_("You cannot change your own role."), "danger")
            return redirect(url_for("admin.users"))
        # The username is fixed; editing covers name, email, role, department.
        user.full_name = form.full_name.data
        user.email = form.email.data
        user.role = form.role.data
        user.department_id = int(form.department.data) if form.department.data else None
        db.session.commit()
        flash(_("User updated."), "success")
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
    return _set_status(user_id, "active", _("User approved."))


@admin_bp.route("/users/<int:user_id>/reject", methods=["POST"])
@login_required
@role_required("admin")
def user_reject(user_id):
    # Rejecting sets "suspended" too, so the same self-lockout guard applies.
    if user_id == current_user.id:
        flash(_("You cannot suspend your own account."), "danger")
        return redirect(url_for("admin.users"))
    return _set_status(user_id, "suspended", _("User rejected."))


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@role_required("admin")
def user_suspend(user_id):
    # Suspending your own account would lock administration out permanently.
    if user_id == current_user.id:
        flash(_("You cannot suspend your own account."), "danger")
        return redirect(url_for("admin.users"))
    return _set_status(user_id, "suspended", _("User suspended."))


@admin_bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@login_required
@role_required("admin")
def user_reactivate(user_id):
    return _set_status(user_id, "active", _("User reactivated."))


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
        flash(_("Password reset."), "success")
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
        flash(_("Department created."), "success")
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
        flash(_("Cannot delete a department that still has users."), "danger")
        return redirect(url_for("admin.departments"))
    # Tickets also hold a foreign key to the department (enforced by SQLite).
    ticket_count = db.session.scalar(
        db.select(db.func.count(Ticket.id)).where(Ticket.department_id == department.id)
    )
    if ticket_count:
        flash(_("Cannot delete a department that still has tickets."), "danger")
        return redirect(url_for("admin.departments"))
    db.session.delete(department)
    db.session.commit()
    flash(_("Department deleted."), "success")
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
        flash(_("Department updated."), "success")
        return redirect(url_for("admin.departments"))
    if not form.is_submitted():
        form.name.data = department.name
    return render_template("admin/department_edit.html", form=form, department=department)


@admin_bp.route("/categories", methods=["GET", "POST"])
@login_required
@role_required("admin")
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        db.session.add(Category(name=form.name.data))
        db.session.commit()
        flash(_("Category created."), "success")
        return redirect(url_for("admin.categories"))
    return render_template(
        "admin/categories.html",
        form=form,
        categories=db.session.scalars(db.select(Category).order_by(Category.name)).all(),
    )


@admin_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def category_delete(category_id):
    category = db.session.get(Category, category_id)
    if category is None:
        abort(404)
    # Tickets hold a foreign key to the category (enforced by SQLite).
    ticket_count = db.session.scalar(
        db.select(db.func.count(Ticket.id)).where(Ticket.category_id == category.id)
    )
    if ticket_count:
        flash(_("Cannot delete a category that still has tickets."), "danger")
        return redirect(url_for("admin.categories"))
    if db.session.scalar(db.select(db.func.count(Category.id))) <= 1:
        flash(_("Cannot delete the last remaining category."), "danger")
        return redirect(url_for("admin.categories"))
    db.session.delete(category)
    db.session.commit()
    flash(_("Category deleted."), "success")
    return redirect(url_for("admin.categories"))


@admin_bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def category_edit(category_id):
    category = db.session.get(Category, category_id)
    if category is None:
        abort(404)
    form = CategoryForm(edit_category=category)
    if form.validate_on_submit():
        category.name = form.name.data
        db.session.commit()
        flash(_("Category updated."), "success")
        return redirect(url_for("admin.categories"))
    if not form.is_submitted():
        form.name.data = category.name
    return render_template("admin/category_edit.html", form=form, category=category)


@admin_bp.route("/branding", methods=["GET", "POST"])
@login_required
@role_required("admin")
def branding():
    try:
        form = BrandingForm()
        validated = form.validate_on_submit()
    except RequestEntityTooLarge:
        # The body is rejected while the form is parsed — before validators can
        # run — so render the same "file too large" page the app-level 413
        # handler uses on the CSRF-enabled production path.
        return branding_upload_error_response()
    if validated:
        set_setting("site_name", form.site_name.data)
        set_setting("accent_color", form.accent_color.data)
        if form.logo.data and form.logo.data.filename:
            _store_logo(form.logo.data)
        flash(_("Branding updated."), "success")
        return redirect(url_for("admin.branding"))
    if not form.is_submitted():
        _prefill_branding_form(form)
    return render_template("admin/branding.html", form=form)


@admin_bp.route("/branding/logo/delete", methods=["POST"])
@login_required
@role_required("admin")
def branding_logo_delete():
    _unlink_logo(get_setting("logo_file"))
    row = db.session.get(Setting, "logo_file")
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    flash(_("Logo removed."), "success")
    return redirect(url_for("admin.branding"))


@admin_bp.route("/backup")
@login_required
@role_required("admin")
def backup_page():
    files = _backup_files()
    return render_template(
        "admin/backup.html",
        backups=[
            {
                "name": path.name,
                "size": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime),
            }
            for path in files
        ],
    )


@admin_bp.route("/backup/create", methods=["POST"])
@login_required
@role_required("admin")
def backup_create():
    try:
        path = run_backup_cycle()
    except (OSError, sqlite3.Error):
        current_app.logger.exception("manual backup failed")
        flash(_("Backup failed. Check the server logs."), "danger")
        return redirect(url_for("admin.backup_page"))
    flash(_("Backup created: {name}").format(name=path.name), "success")
    return redirect(url_for("admin.backup_page"))


@admin_bp.route("/backup/<name>/download")
@login_required
@role_required("admin")
def backup_download(name):
    # Traversal guard: only exactly named backup files, and after resolving
    # symlinks/".." the target must still sit directly inside BACKUP_DIR.
    if not re.fullmatch(r"ttks_dps-\d{8}-\d{6}\.db", name):
        abort(404)
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    target = (backup_dir / name).resolve()
    if target.parent != backup_dir.resolve():
        abort(404)
    if not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True)


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


def _prefill_branding_form(form: BrandingForm) -> None:
    """Fill the form from the current settings (only when rendering, never after a POST)."""
    branding = get_branding()
    form.site_name.data = branding["site_name"]
    form.accent_color.data = branding["accent_color"]


def _branding_dir() -> Path:
    return Path(current_app.config["DATA_DIR"]) / "branding"


def _unlink_logo(name: str | None) -> None:
    """Unlink a stored logo file; nothing outside the branding dir is ever touched."""
    if not name or Path(name).name != name:
        return
    (_branding_dir() / name).unlink(missing_ok=True)


def _store_logo(file) -> None:
    """Store the upload as ``logo{ext}`` per the upload rule, replacing any old logo.

    Only called once the form (and its logo validation) has fully passed.
    """
    branding_dir = _branding_dir()
    branding_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(secure_filename(file.filename)).suffix.lower()
    stored = f"logo{ext}"
    old_name = get_setting("logo_file")
    file.save(branding_dir / stored)
    if old_name != stored:
        _unlink_logo(old_name)
    set_setting("logo_file", stored)
