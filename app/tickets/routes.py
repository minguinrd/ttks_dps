from datetime import UTC, datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.durations import format_duration, resolution_time
from app.extensions import db
from app.i18n import _
from app.models import (
    Category,
    Comment,
    Department,
    InvalidTransition,
    Notification,
    Role,
    Ticket,
    TicketStatus,
    User,
)
from app.notifications import notify
from app.permissions import role_required
from app.search import LIKE_ESCAPE, like_pattern
from app.tickets import tickets_bp
from app.tickets.forms import AssignForm, CommentForm, ResolveForm, TicketEditForm, TicketForm

INVALID_TRANSITION_MESSAGE = _("This action is not allowed for the current ticket status.")


_ACTIVE = (TicketStatus.open, TicketStatus.assigned)

# "Mine" tabs: active work first; resolved tickets wait for the requester.
MINE_TABS = ("active", "resolved", "closed", "all")
MINE_SCOPES = ("all", "requested", "assigned")
MINE_PER_PAGE = 25


@tickets_bp.route("/mine")
@login_required
def mine():
    is_staff = current_user.role != Role.user
    scope = request.args.get("scope", "all")
    if scope not in MINE_SCOPES or not is_staff:
        scope = "all"
    status = request.args.get("status", "") or "active"
    if status not in MINE_TABS:
        status = "active"
    search = request.args.get("q", "").strip()[:100]

    if scope == "requested":
        filters = [Ticket.requester_id == current_user.id]
    elif scope == "assigned":
        filters = [Ticket.assignee_id == current_user.id]
    else:
        filters = [
            (Ticket.requester_id == current_user.id) | (Ticket.assignee_id == current_user.id)
        ]
    if search:
        number = search.removeprefix("#")
        text = Ticket.subject.ilike(like_pattern(search), escape=LIKE_ESCAPE)
        filters.append((Ticket.id == int(number)) | text if number.isdigit() else text)

    counts = {value.value: 0 for value in TicketStatus}
    for value, count in db.session.execute(
        db.select(Ticket.status, db.func.count(Ticket.id)).where(*filters).group_by(Ticket.status)
    ):
        counts[value] = count
    counts["active"] = counts["open"] + counts["assigned"]
    counts["all"] = sum(counts[value.value] for value in TicketStatus)

    query = Ticket.list_query().where(*filters)
    if status == "active":
        query = query.where(Ticket.status.in_(_ACTIVE))
    elif status != "all":
        query = query.where(Ticket.status == status)
    page = db.paginate(
        query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()),
        page=request.args.get("page", 1, type=int),
        per_page=MINE_PER_PAGE,
        error_out=False,
    )

    fresh = _fresh_ticket_ids()
    # Resolved tickets the viewer requested are waiting for their confirmation.
    awaiting = db.session.scalar(
        db.select(db.func.count(Ticket.id)).where(
            Ticket.requester_id == current_user.id, Ticket.status == TicketStatus.resolved
        )
    )
    return render_template(
        "tickets/mine.html",
        tickets=page.items,
        page=page,
        status=status,
        scope=scope,
        search=search,
        counts=counts,
        fresh=fresh,
        awaiting=awaiting,
        is_staff=is_staff,
        now=_naive_utc_now(),
    )


# Queue tabs: "active" (the default) is the work still to do.
QUEUE_TABS = ("active", "open", "assigned", "resolved", "closed", "all")
QUEUE_PER_PAGE = 50
# Most pressing first; unknown values sort last.
_PRIORITY_RANK = db.case(
    {"urgent": 0, "high": 1, "normal": 2, "low": 3}, value=Ticket.priority, else_=4
)
QUEUE_SORTS = {
    "priority": (_PRIORITY_RANK, Ticket.created_at.asc()),
    "oldest": (Ticket.created_at.asc(),),
    "newest": (Ticket.created_at.desc(),),
    "updated": (Ticket.updated_at.desc(),),
}


def _queue_filters(args) -> list:
    """Every queue filter except the status tab, as SQL conditions."""
    filters = []
    if category_id := args.get("category_id", type=int):
        filters.append(Ticket.category_id == category_id)
    if priority := args.get("priority", ""):
        filters.append(Ticket.priority == priority)
    if department_id := args.get("department_id", type=int):
        filters.append(Ticket.department_id == department_id)
    if requester_id := args.get("requester_id", type=int):
        filters.append(Ticket.requester_id == requester_id)
    assignee = args.get("assignee", "")
    if assignee == "me":
        filters.append(Ticket.assignee_id == current_user.id)
    elif assignee == "none":
        filters.append(Ticket.assignee_id.is_(None))
    elif assignee.isdigit():
        filters.append(Ticket.assignee_id == int(assignee))
    search = args.get("q", "").strip()[:100]
    if search:
        # "#42" or "42" also finds ticket 42 by number.
        number = search.removeprefix("#")
        pattern = like_pattern(search)
        text = Ticket.subject.ilike(pattern, escape=LIKE_ESCAPE) | Ticket.description.ilike(
            pattern, escape=LIKE_ESCAPE
        )
        filters.append((Ticket.id == int(number)) | text if number.isdigit() else text)
    return filters


@tickets_bp.route("/queue")
@login_required
@role_required("agent", "admin")
def queue():
    # Every filter except status narrows the list; the status tabs then show
    # how many of those tickets sit in each state.
    filters = _queue_filters(request.args)
    status = request.args.get("status", "") or "active"
    if status not in QUEUE_TABS:
        status = "active"
    sort = request.args.get("sort", "priority")
    if sort not in QUEUE_SORTS:
        sort = "priority"

    status_counts = {status.value: 0 for status in TicketStatus}
    for value, count in db.session.execute(
        db.select(Ticket.status, db.func.count(Ticket.id)).where(*filters).group_by(Ticket.status)
    ):
        status_counts[value] = count
    status_counts["active"] = status_counts["open"] + status_counts["assigned"]
    status_counts["all"] = sum(status_counts[value.value] for value in TicketStatus)

    query = Ticket.list_query().where(*filters)
    if status == "active":
        query = query.where(Ticket.status.in_(_ACTIVE))
    elif status != "all":
        query = query.where(Ticket.status == status)
    page = db.paginate(
        query.order_by(*QUEUE_SORTS[sort], Ticket.id.desc()),
        page=request.args.get("page", 1, type=int),
        per_page=QUEUE_PER_PAGE,
        error_out=False,
    )
    staff = db.session.scalars(
        db.select(User)
        .where(User.role.in_((Role.agent, Role.admin)), User.status == "active")
        .order_by(User.username)
    ).all()
    return render_template(
        "tickets/queue.html",
        tickets=page.items,
        page=page,
        status=status,
        sort=sort,
        search=request.args.get("q", "").strip()[:100],
        status_counts=status_counts,
        now=_naive_utc_now(),
        departments=db.session.scalars(db.select(Department).order_by(Department.name)).all(),
        categories=db.session.scalars(db.select(Category).order_by(Category.name)).all(),
        users=db.session.scalars(db.select(User).order_by(User.username)).all(),
        staff=staff,
        fresh=_fresh_ticket_ids(),
    )


def _fresh_ticket_ids() -> set[int]:
    """Tickets with an unread notification for the viewer ("New update" mark)."""
    return set(
        db.session.scalars(
            db.select(Notification.ticket_id).where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
                Notification.ticket_id.is_not(None),
            )
        )
    )


def _naive_utc_now() -> datetime:
    """``now`` in the shape SQLite hands back (naive UTC), so templates can subtract."""
    return datetime.now(UTC).replace(tzinfo=None)


@tickets_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = TicketForm()
    if form.validate_on_submit():
        ticket = Ticket(
            subject=form.subject.data,
            description=form.description.data,
            category_id=form.category_id.data,
            priority=form.priority.data,
            status=TicketStatus.open,
            requester_id=current_user.id,
            department_id=current_user.department_id,
        )
        db.session.add(ticket)
        db.session.commit()
        flash(_("Ticket created."), "success")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    return render_template("tickets/form.html", form=form)


@tickets_bp.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    # Opening the ticket is reading about it: clear this viewer's pings for it.
    db.session.execute(
        db.update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.ticket_id == ticket.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    db.session.commit()
    return _render_detail(ticket)


@tickets_bp.route("/<int:ticket_id>/comments", methods=["POST"])
@login_required
def comment(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if ticket.status == TicketStatus.closed:
        abort(403)
    form = CommentForm()
    if form.validate_on_submit():
        # Regular users can never create internal notes, even when forged.
        is_internal = form.is_internal.data and current_user.role != Role.user
        db.session.add(
            Comment(
                ticket_id=ticket.id,
                author_id=current_user.id,
                body=form.body.data,
                is_internal=is_internal,
            )
        )
        # Internal notes are for agents only: they never notify anyone.
        if not is_internal:
            # The actor never pings themselves.
            notify(
                [user_id for user_id in _comment_recipients(ticket) if user_id != current_user.id],
                f"New comment on ticket #{ticket.id}.",
                url_for("tickets.detail", ticket_id=ticket.id),
                ticket_id=ticket.id,
                key="New comment on ticket #{ticket_id}.",
                params={"ticket_id": ticket.id},
            )
        db.session.commit()
        flash(_("Comment posted."), "success")
    else:
        flash(_("Comment text is required."), "danger")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/edit", methods=["POST"])
@login_required
def edit(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if not _can_edit(ticket):
        abort(403)
    form = TicketEditForm()
    if form.validate_on_submit():
        ticket.subject = form.subject.data
        ticket.description = form.description.data
        ticket.category_id = form.category_id.data
        ticket.priority = form.priority.data
        db.session.commit()
        flash(_("Ticket updated."), "success")
    else:
        flash(_("All fields are required."), "danger")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/claim", methods=["POST"])
@login_required
def claim(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if current_user.role not in (Role.agent, Role.admin):
        abort(403)
    try:
        ticket.claim(current_user)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    notify(
        [ticket.assignee.id],
        f"Ticket #{ticket.id} has been assigned to you.",
        url_for("tickets.detail", ticket_id=ticket.id),
        ticket_id=ticket.id,
        key="Ticket #{ticket_id} has been assigned to you.",
        params={"ticket_id": ticket.id},
    )
    db.session.commit()
    flash(_("Ticket claimed."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/release", methods=["POST"])
@login_required
def release(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if current_user.id != ticket.assignee_id and current_user.role != Role.admin:
        abort(403)
    try:
        ticket.release(current_user)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash(_("Ticket released."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/assign", methods=["POST"])
@login_required
def assign(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if current_user.role != Role.admin:
        abort(403)
    form = _assign_form()
    if not form.validate_on_submit():
        flash(_("Select a valid agent."), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    agent = db.session.get(User, form.agent_id.data)
    if agent is None or not agent.is_active:
        # Suspended/pending targets are not assignable even if forged past the
        # choice list.
        flash(_("Select a valid agent."), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    try:
        ticket.assign_to(agent, current_user)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    notify(
        [agent.id],
        f"Ticket #{ticket.id} has been assigned to you.",
        url_for("tickets.detail", ticket_id=ticket.id),
        ticket_id=ticket.id,
        key="Ticket #{ticket_id} has been assigned to you.",
        params={"ticket_id": ticket.id},
    )
    db.session.commit()
    flash(_("Ticket assigned."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/resolve", methods=["POST"])
@login_required
def resolve(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if current_user.id != ticket.assignee_id and current_user.role != Role.admin:
        abort(403)
    form = ResolveForm()
    if not form.validate_on_submit():
        return _render_detail(ticket, resolve_form=form)
    try:
        ticket.resolve(current_user, form.resolution_note.data)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    notify(
        [ticket.requester_id],
        f"Ticket #{ticket.id} has been resolved.",
        url_for("tickets.detail", ticket_id=ticket.id),
        ticket_id=ticket.id,
        key="Ticket #{ticket_id} has been resolved.",
        params={"ticket_id": ticket.id},
    )
    db.session.commit()
    flash(_("Ticket resolved."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/reopen", methods=["POST"])
@login_required
def reopen(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if not _can_reopen(ticket):
        abort(403)
    try:
        ticket.reopen(current_user)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    body = request.form.get("comment", "").strip()
    if body:
        db.session.add(Comment(ticket_id=ticket.id, author_id=current_user.id, body=body))
    # Reopening notifies the counterpart: the requester when an agent/admin
    # acts, otherwise the assignee (the requester is the actor in that case).
    if current_user.role in (Role.agent, Role.admin) and ticket.requester_id != current_user.id:
        reopen_recipient_ids = [ticket.requester_id]
    else:
        reopen_recipient_ids = [ticket.assignee_id] if ticket.assignee_id else []
    notify(
        reopen_recipient_ids,
        f"Ticket #{ticket.id} has been reopened.",
        url_for("tickets.detail", ticket_id=ticket.id),
        ticket_id=ticket.id,
        key="Ticket #{ticket_id} has been reopened.",
        params={"ticket_id": ticket.id},
    )
    db.session.commit()
    flash(_("Ticket reopened."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/close", methods=["POST"])
@login_required
def close(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    is_participant = current_user.id in (ticket.requester_id, ticket.assignee_id)
    if not is_participant and current_user.role not in (Role.agent, Role.admin):
        abort(403)
    try:
        ticket.close(current_user)
    except InvalidTransition:
        flash(_(INVALID_TRANSITION_MESSAGE), "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    notify(
        [ticket.requester_id],
        f"Ticket #{ticket.id} has been closed.",
        url_for("tickets.detail", ticket_id=ticket.id),
        ticket_id=ticket.id,
        key="Ticket #{ticket_id} has been closed.",
        params={"ticket_id": ticket.id},
    )
    db.session.commit()
    flash(_("Ticket closed."), "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


def _comment_recipients(ticket: Ticket) -> list[int]:
    """Requester and assignee ids (whichever exist) for a public comment."""
    return sorted({user_id for user_id in (ticket.requester_id, ticket.assignee_id) if user_id})


def _visible_ticket_or_404(ticket_id: int) -> Ticket:
    """Fetch a ticket; regular users only see tickets they request or are assigned (else 404)."""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        abort(404)
    if current_user.role == Role.user and current_user.id not in (
        ticket.requester_id,
        ticket.assignee_id,
    ):
        abort(404)
    return ticket


def _can_edit(ticket: Ticket) -> bool:
    """Requester may edit only while open; agents/admins any status except closed."""
    if ticket.status == TicketStatus.closed:
        return False
    if current_user.role != Role.user:
        return True
    return ticket.requester_id == current_user.id and ticket.status == TicketStatus.open


def _can_reopen(ticket: Ticket) -> bool:
    """Admin reopens closed tickets; resolved ones may also be reopened by requester/agent."""
    if ticket.status == TicketStatus.closed:
        return current_user.role == Role.admin
    return current_user.id == ticket.requester_id or current_user.role in (Role.agent, Role.admin)


def _assign_form() -> AssignForm:
    """Assign form with choices seeded with the active agent/admin users."""
    form = AssignForm()
    agents = db.session.scalars(
        db.select(User)
        .where(User.role.in_((Role.agent, Role.admin)), User.status == "active")
        .order_by(User.username)
    ).all()
    form.agent_id.choices = [(0, _("Select an agent…"))] + [
        (agent.id, agent.full_name or agent.username) for agent in agents
    ]
    return form


def _render_detail(ticket: Ticket, resolve_form: ResolveForm | None = None):
    """Render the detail page; ``resolve_form`` carries errors when re-rendered after a failure."""
    # Internal notes are stripped server-side for regular users, never just hidden.
    comments = [
        comment
        for comment in ticket.comments
        if current_user.role != Role.user or not comment.is_internal
    ]
    # Staff get the requester's other recent tickets as context.
    related = []
    if current_user.role != Role.user:
        related = db.session.scalars(
            db.select(Ticket)
            .where(Ticket.requester_id == ticket.requester_id, Ticket.id != ticket.id)
            .order_by(Ticket.created_at.desc())
            .limit(5)
        ).all()
    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        comments=comments,
        public_count=sum(1 for comment in comments if not comment.is_system),
        related=related,
        resolution_time=resolution_time(ticket),
        duration=format_duration,
        comment_form=CommentForm(),
        edit_form=TicketEditForm(obj=ticket),
        can_edit=_can_edit(ticket),
        resolve_form=resolve_form or ResolveForm(),
        assign_form=_assign_form(),
    )
