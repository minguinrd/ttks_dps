from flask import flash, redirect, render_template, url_for
from flask_login import login_required, login_user, logout_user

from app.auth import auth_bp
from app.auth.forms import LoginForm, RegisterForm
from app.extensions import db
from app.models import User


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            full_name=form.full_name.data,
            email=form.email.data,
            department_id=int(form.department.data) if form.department.data else None,
            status="pending",
            role="user",
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("auth.pending"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/pending")
def pending():
    return render_template("auth/pending.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).filter_by(username=form.username.data))
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.", "danger")
        elif user.status == "pending":
            flash("Your account is awaiting admin approval.", "warning")
        elif user.status == "suspended":
            flash("This account has been suspended. Contact the administrator.", "danger")
        else:
            login_user(user)
            return redirect(url_for("main.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
