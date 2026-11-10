import os

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import User


@click.command("seed-admin")
@with_appcontext
def seed_admin() -> None:
    """Create the initial admin account from ADMIN_USERNAME and ADMIN_PASSWORD."""
    if db.session.scalar(db.select(User).where(User.role == "admin")) is not None:
        click.echo("admin already exists")
        return

    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        raise click.ClickException("ADMIN_USERNAME and ADMIN_PASSWORD are required")

    user = User(username=username, role="admin", status="active", must_change_password=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"created admin user {username}")
