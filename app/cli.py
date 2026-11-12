import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from app.backup import db_path_from_uri
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


@click.command("restore-backup")
@click.argument("path", type=click.Path(exists=False))
@with_appcontext
def restore_backup(path: str) -> None:
    """Restore the live SQLite database from the backup file at PATH.

    Runs an integrity check first, keeps a safety copy of the current
    database, swaps the backup in, and clears stale WAL sidecar files.
    """
    source = Path(path)
    if not source.is_file():
        raise click.ClickException(f"backup file not found: {path}")
    if not _passes_integrity_check(source):
        raise click.ClickException(f"backup failed integrity check: {path}")
    live = db_path_from_uri(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if source.resolve() == live.resolve():
        raise click.ClickException("refusing to restore the live database over itself")
    if live.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(live, Path(current_app.config["DATA_DIR"]) / f"pre-restore-{stamp}.db")
    shutil.copy2(source, live)
    for sidecar in (Path(f"{live}-wal"), Path(f"{live}-shm")):
        sidecar.unlink(missing_ok=True)
    click.echo(f"restored {live} from {source}")
    click.echo("Restart the service to apply the restored database.")


def _passes_integrity_check(path: Path) -> bool:
    """True when PATH is a readable SQLite database with no integrity errors."""
    try:
        conn = sqlite3.connect(path)
        try:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error:
        return False
