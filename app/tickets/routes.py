from datetime import datetime, timezone

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Comment, Department, InvalidTransition, Role, Ticket, TicketStatus, User
from app.permissions import role_required
from app.tickets import tickets_bp
from app.tickets.forms import AssignForm, CommentForm, ResolveForm, TicketEditForm, TicketForm

INVALID_TRANSITION_MESSAGE = "This action is not allowed for the current ticket status."


@tickets_bp.route("/mine")
@login_required
def mine():
    tickets = db.session.scalars(
        db.select(Ticket)
        .where((Ticket.requester_id == current_user.id) | (Ticket.assignee_id == current_user.id))
        .order_by(Ticket.created_at.desc())
    ).all()
    return render_template("tickets/mine.html", tickets=tickets)


@tickets_bp.route("/queue")
@login_required
@role_required("agent", "admin")
def queue():
    query = db.select(Ticket).order_by(Ticket.created_at.desc())
    status = request.args.get("status", "")
    if status:
        query = query.where(Ticket.status == status)
    category = request.args.get("category", "")
    if category:
        query = query.where(Ticket.category == category)
    priority = request.args.get("priority", "")
    if priority:
        query = query.where(Ticket.priority == priority)
    department_id = request.args.get("department_id", type=int)
    if department_id:
        query = query.where(Ticket.department_id == department_id)
    requester_id = request.args.get("requester_id", type=int)
    if requester_id:
        query = query.where(Ticket.requester_id == requester_id)
    return render_template(
        "tickets/queue.html",
        tickets=db.session.scalars(query).all(),
        # SQLite hands back naive UTC datetimes; keep ``now`` naive so the age column can subtract.
        now=datetime.now(timezone.utc).replace(tzinfo=None),
        departments=db.session.scalars(db.select(Department).order_by(Department.name)).all(),
        users=db.session.scalars(db.select(User).order_by(User.username)).all(),
    )


@tickets_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = TicketForm()
    if form.validate_on_submit():
        ticket = Ticket(
            subject=form.subject.data,
            description=form.description.data,
            category=form.category.data,
            priority=form.priority.data,
            status=TicketStatus.open,
            requester_id=current_user.id,
            department_id=current_user.department_id,
        )
        db.session.add(ticket)
        db.session.commit()
        flash("Ticket created.", "success")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    return render_template("tickets/form.html", form=form)


@tickets_bp.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    return _render_detail(_visible_ticket_or_404(ticket_id))


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
        db.session.commit()
        flash("Comment posted.", "success")
    else:
        flash("Comment text is required.", "danger")
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
        ticket.category = form.category.data
        ticket.priority = form.priority.data
        db.session.commit()
        flash("Ticket updated.", "success")
    else:
        flash("All fields are required.", "danger")
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
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash("Ticket claimed.", "success")
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
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash("Ticket released.", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/assign", methods=["POST"])
@login_required
def assign(ticket_id):
    ticket = _visible_ticket_or_404(ticket_id)
    if current_user.role != Role.admin:
        abort(403)
    form = _assign_form()
    if not form.validate_on_submit():
        flash("Select a valid agent.", "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    agent = db.session.get(User, form.agent_id.data)
    try:
        ticket.assign_to(agent, current_user)
    except InvalidTransition:
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash("Ticket assigned.", "success")
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
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash("Ticket resolved.", "success")
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
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    body = request.form.get("comment", "").strip()
    if body:
        db.session.add(Comment(ticket_id=ticket.id, author_id=current_user.id, body=body))
    db.session.commit()
    flash("Ticket reopened.", "success")
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
        flash(INVALID_TRANSITION_MESSAGE, "danger")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    db.session.commit()
    flash("Ticket closed.", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


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
    """Assign form with choices seeded with the agent/admin users."""
    form = AssignForm()
    agents = db.session.scalars(
        db.select(User).where(User.role.in_((Role.agent, Role.admin))).order_by(User.username)
    ).all()
    form.agent_id.choices = [(0, "Select an agent…")] + [
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
    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        comments=comments,
        comment_form=CommentForm(),
        edit_form=TicketEditForm(obj=ticket),
        can_edit=_can_edit(ticket),
        resolve_form=resolve_form or ResolveForm(),
        assign_form=_assign_form(),
    )
