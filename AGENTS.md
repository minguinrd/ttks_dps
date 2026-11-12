# Agent notes (ttks_dps)

## Stack

Flask 3 + Flask-SQLAlchemy + Flask-Login + Flask-WTF (CSRF) + Flask-Migrate
(Alembic) over SQLite (WAL), served by gunicorn in Docker. Tests: pytest.
Lint/format: ruff. Python 3.11+ syntax is fine (ruff `target-version = "py311"`).

## Commands (run from repo root; venv is `.venv/`)

- `.venv/bin/flask --app wsgi db upgrade` — apply migrations
- `.venv/bin/flask --app wsgi seed-admin` — idempotent; needs `ADMIN_USERNAME` + `ADMIN_PASSWORD` in the environment
- `.venv/bin/flask --app wsgi restore-backup <path>` — swap a backup in (integrity check, safety copy, WAL cleanup); stop the service first
- `.venv/bin/flask --app wsgi run` — dev server
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
- `docker compose up --build` — image on port 8000, data in volume `ttks_data:/data`

## Layout

Blueprints in `app/{auth,main,tickets,admin}` (wired in `app/__init__.py`),
models in `app/models/` (user, ticket, notification), Alembic migrations in
`migrations/`, templates in `app/templates/`, deployment in `Dockerfile`,
`docker/entrypoint.sh`, `docker-compose.yml`.

## Gotchas

- `app/extensions.py` installs a SQLite connect listener: WAL journal +
  `foreign_keys=ON` on every connection.
- Env vars (see `.env.example`): `FLASK_APP`, `SECRET_KEY`, `DATA_DIR`,
  `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `BACKUP_HOUR` / `BACKUP_KEEP` (daily
  SQLite backup schedule; defaults `03:00` / `7`), plus optional
  `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (both set gates the Google
  login button and `/auth/google` routes). `flask seed-admin` errors without the
  `ADMIN_*` pair; `flask` CLI does not load `.env` unless python-dotenv is
  installed (export the vars or use `--app`).
- Frontend assets come from CDNs (Bootstrap 5 + SweetAlert2 in
  `app/templates/base.html`) — no local asset pipeline.
- No email: notifications are in-app rows only (`app/notifications.py`).
- The ticket status machine lives on `Ticket` (`app/models/ticket.py`) and
  raises `InvalidTransition` on illegal moves — catch it in routes, never
  mutate `Ticket.status` directly.
- i18n: mark every user-visible literal with `_()` (`{{ _("...") }}` in
  templates, `from app.i18n import _` in Python) and translate it in
  `app/locales/es.json`. Keys are always literal strings — never f-strings or
  concatenation. `tests/test_i18n_completeness.py` enforces both directions
  (run it after touching any UI string).
