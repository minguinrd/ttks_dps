from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Comment, Role, Ticket, TicketStatus
from app.tickets import tickets_bp
from app.tickets.forms import CommentForm, TicketEditForm, TicketForm


@tickets_bp.route("/mine")
@login_required
def mine():
    tickets = db.session.scalars(
        db.select(Ticket)
        .where((Ticket.requester_id == current_user.id) | (Ticket.assignee_id == current_user.id))
        .order_by(Ticket.created_at.desc())
    ).all()
    return render_template("tickets/mine.html", tickets=tickets)


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
    ticket = _visible_ticket_or_404(ticket_id)
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
    )


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
