import os


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment ("1", "true", "yes", "on")."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Required: create_app refuses to start without it (see .env.example).
    SECRET_KEY = os.environ.get("SECRET_KEY")
    # Resolve to an absolute path so the SQLite URI and the factory's makedirs target
    # the same directory (Flask-SQLAlchemy resolves relative SQLite paths against the
    # Flask instance path, not the cwd).
    DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR}/ttks_dps.db"
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    AVATAR_DIR = f"{DATA_DIR}/avatars"
    WTF_CSRF_ENABLED = True
    # Cookie hardening. SESSION_COOKIE_SECURE must be on whenever the app is
    # served over HTTPS (it is off by default so plain-HTTP local/Docker use
    # keeps working).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    # Number of reverse proxies in front of the app whose X-Forwarded-* headers
    # are trusted (0 = none). Needed behind nginx/Traefik so external URLs
    # (e.g. the Google OAuth redirect URI) get the right scheme and host.
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0"))
    # Optional Google sign-in (Authlib reads these via its GOOGLE_* config
    # convention). Both must be non-empty to enable the button and routes.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    # Daily SQLite backups (app/backup.py): run at BACKUP_HOUR ("HH:MM", local
    # time), keep the newest BACKUP_KEEP files in BACKUP_DIR.
    BACKUP_HOUR = os.environ.get("BACKUP_HOUR", "03:00")
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "7"))
    BACKUP_DIR = os.path.join(DATA_DIR, "backups")
