"""SQLite backups: snapshot via ``VACUUM INTO``, pruning, and the daily scheduler.

``run_backup_cycle`` is the shared entry point for the admin "Back up now"
button and the scheduler thread started by ``create_app``.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, current_app


def db_path_from_uri(uri: str) -> Path:
    """Map a SQLAlchemy SQLite URI to its database file path.

    Same rule as ``tests/test_migrations.py::_db_path``: strip the
    ``sqlite:///`` prefix.
    """
    return Path(uri.removeprefix("sqlite:///"))


def create_backup() -> Path:
    """Snapshot the live database into ``BACKUP_DIR`` and return the new file.

    ``VACUUM INTO`` writes a compacted, consistent copy of the database the
    live connection points at; the target must not exist yet. Needs an app
    context (reads ``BACKUP_DIR`` and ``SQLALCHEMY_DATABASE_URI``).
    """
    backup_dir = Path(current_app.config["BACKUP_DIR"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"ttks_dps-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
    conn = sqlite3.connect(db_path_from_uri(current_app.config["SQLALCHEMY_DATABASE_URI"]))
    try:
        # SQLite evaluates the target as an expression, so a bound parameter works.
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()
    return target


def prune_backups(keep: int) -> int:
    """Delete the oldest ``ttks_dps-*.db`` files beyond ``keep``; return the count.

    Timestamped names sort lexicographically, so plain name order is
    chronological. Needs an app context (reads ``BACKUP_DIR``).
    """
    files = sorted(Path(current_app.config["BACKUP_DIR"]).glob("ttks_dps-*.db"))
    doomed = files if keep <= 0 else files[:-keep]
    for path in doomed:
        path.unlink()
    return len(doomed)


def run_backup_cycle() -> Path:
    """Take a backup and prune old ones; shared entry point for scheduler and admin."""
    path = create_backup()
    prune_backups(current_app.config["BACKUP_KEEP"])
    return path


def start_scheduler(app: Flask) -> None:
    """Run ``run_backup_cycle`` daily at ``BACKUP_HOUR`` in a daemon thread.

    The next run time is recomputed after every cycle; per-cycle errors are
    logged and swallowed so the thread survives them.
    """

    def _loop() -> None:
        while True:
            time.sleep(_seconds_until_next(app.config["BACKUP_HOUR"]))
            try:
                with app.app_context():
                    run_backup_cycle()
            except Exception:
                app.logger.exception("scheduled backup cycle failed")

    threading.Thread(target=_loop, name="backup-scheduler", daemon=True).start()


def _seconds_until_next(hour: str, now: datetime | None = None) -> float:
    """Seconds from ``now`` until the next occurrence of ``hour`` ("HH:MM")."""
    hh, mm = map(int, hour.split(":"))
    now = now or datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
