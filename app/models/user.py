from datetime import datetime, timezone
from enum import StrEnum

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class Role(StrEnum):
    user = "user"
    agent = "agent"
    admin = "admin"


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    users = db.relationship("User", back_populates="department")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120))
    email = db.Column(db.String(255))
    # Google account id (OIDC ``sub``) once a Google sign-in is linked.
    google_sub = db.Column(db.String(64), unique=True, nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    status = db.Column(db.String(20), nullable=False, default="pending")
    role = db.Column(db.String(20), nullable=False, default="user")
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    avatar_path = db.Column(db.String(255))
    # UI display language ("en" / "es" — see app.i18n.SUPPORTED).
    language = db.Column(db.String(5), nullable=False, default="en", server_default="en")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    department = db.relationship("Department", back_populates="users")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

    @property
    def is_active(self) -> bool:
        return self.status == "active"
