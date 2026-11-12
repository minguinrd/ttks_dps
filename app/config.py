import os


class Config:
    # Required in production use: set SECRET_KEY in the environment (see .env.example).
    SECRET_KEY = os.environ.get("SECRET_KEY")
    # Resolve to an absolute path so the SQLite URI and the factory's makedirs target
    # the same directory (Flask-SQLAlchemy resolves relative SQLite paths against the
    # Flask instance path, not the cwd).
    DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR}/ttks_dps.db"
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    AVATAR_DIR = f"{DATA_DIR}/avatars"
    WTF_CSRF_ENABLED = True
    # Optional Google sign-in (Authlib reads these via its GOOGLE_* config
    # convention). Both must be non-empty to enable the button and routes.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    # Daily SQLite backups (app/backup.py): run at BACKUP_HOUR ("HH:MM", local
    # time), keep the newest BACKUP_KEEP files in BACKUP_DIR.
    BACKUP_HOUR = os.environ.get("BACKUP_HOUR", "03:00")
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "7"))
    BACKUP_DIR = os.path.join(DATA_DIR, "backups")


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{Config.DATA_DIR}/ttks_dps_test.db"
