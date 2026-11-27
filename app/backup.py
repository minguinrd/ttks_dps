"""SQLite backups: snapshot via ``VACUUM INTO``, pruning, and the daily scheduler.

``run_backup_cycle`` is the shared entry point for the admin "Back up now"
button and the scheduler thread started by ``create_app``.

``create_app`` runs once per gunicorn worker (and per ``flask`` CLI call), so
several schedulers may be alive at once. Only the one holding an exclusive
lock on ``BACKUP_DIR/.scheduler.lock`` takes the daily backup; the others
retry the lock each cycle, so a dead leader is replaced on the next run.
"""

import os
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import Flask, current_app

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX dev machines
    fcntl = None

_HOUR_FORMAT = "HH:MM"


def parse_backup_hour(hour: str) -> tuple[int, int]:
    """Parse ``BACKUP_HOUR`` ("HH:MM", 24h) or raise ``ValueError``."""
    try:
        hh, mm = (int(part) for part in hour.split(":"))
    except (AttributeError, ValueError):
        raise ValueError(f"BACKUP_HOUR must be {_HOUR_FORMAT}, got {hour!r}") from None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"BACKUP_HOUR must be {_HOUR_FORMAT}, got {hour!r}")
    return hh, mm


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
    target = backup_dir / f"ttks_dps-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
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
    logged and swallowed so the thread survives them. Only the process that
    holds the scheduler lock (see the module docstring) runs the cycle.
    """
    lock_path = Path(app.config["BACKUP_DIR"]) / ".scheduler.lock"

    def _loop() -> None:
        lock_fd: int | None = None
        while True:
            time.sleep(_seconds_until_next(app.config["BACKUP_HOUR"]))
            try:
                if lock_fd is None:
                    lock_fd = _try_acquire_lock(lock_path)
                    if lock_fd is None:
                        continue  # another process is the scheduler leader
                with app.app_context():
                    run_backup_cycle()
            except Exception:
                app.logger.exception("scheduled backup cycle failed")

    threading.Thread(target=_loop, name="backup-scheduler", daemon=True).start()


def _try_acquire_lock(path: Path) -> int | None:
    """Take an exclusive, non-blocking lock on ``path``; return the fd or ``None``.

    The fd is kept open for the life of the process: the OS drops the lock
    when the process exits, letting another worker take over.
    """
    if fcntl is None:  # pragma: no cover - no cross-process lock available
        return -1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _seconds_until_next(hour: str, now: datetime | None = None) -> float:
    """Seconds from ``now`` until the next occurrence of ``hour`` ("HH:MM")."""
    hh, mm = parse_backup_hour(hour)
    now = now or datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
