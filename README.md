# ttks_dps — ticketing webapp

A small Flask helpdesk app: users open support tickets, agents work a shared
queue (claim, assign, resolve, reopen), admins manage users and departments.
SQLite database, in-app notifications only — no email is ever sent.

## Roles

- **user** — open tickets, track and comment on their own tickets
- **agent** — work the queue: claim, release, resolve and reopen tickets
- **admin** — agent powers plus assigning tickets and managing users/departments

## Local development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
set -a; . ./.env; set +a   # the flask CLI reads config from the environment
flask db upgrade           # apply migrations
flask seed-admin           # idempotent; creates the ADMIN_* account (must change password on first login)
flask run                  # http://localhost:5000
```

## Verification

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

## Docker

```sh
cp .env.example .env       # set SECRET_KEY and ADMIN_* first
docker compose up --build
```

The app is served by gunicorn on **http://localhost:8000**. Migrations run and
the admin account is seeded on every start (both are idempotent). The SQLite
database and avatar uploads live in the `ttks_data` volume mounted at `/data`;
`docker compose down` keeps that volume.

## Environment variables

Pinned in `.env.example` and read by `app/config.py`:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session/CSRF signing key — set a long random value |
| `DATA_DIR` | Where the SQLite DB and avatars live (default `./data`, `/data` in Docker) |
| `ADMIN_USERNAME` | Initial admin created by `flask seed-admin` |
| `ADMIN_PASSWORD` | Initial admin password (forced change on first login) |

`FLASK_APP=wsgi:app` is also set there for the flask CLI (the Docker image sets
it itself).
