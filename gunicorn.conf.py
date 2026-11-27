"""Gunicorn settings (used by docker/entrypoint.sh); each one can be overridden by env."""

import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
# SQLite allows a single writer: a few sync workers are plenty for a helpdesk.
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
# Log to stdout/stderr so `docker compose logs` shows requests and errors.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# Heartbeat files on tmpfs instead of the container's overlay filesystem.
worker_tmp_dir = "/dev/shm"
