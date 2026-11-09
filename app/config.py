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


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{Config.DATA_DIR}/ttks_dps_test.db"
