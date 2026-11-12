# ttks_dps — ticketing webapp

A small Flask helpdesk app: users open support tickets, agents work a shared
queue (claim, assign, resolve, reopen), admins manage users and departments.
SQLite database, in-app notifications only — no email is ever sent.

## Roles

- **user** — open tickets, track and comment on their own tickets
- **agent** — work the queue: claim, release, resolve and reopen tickets
- **admin** — agent powers plus assigning tickets and managing users/departments;
  admins also set the site name, logo, and accent color at **Admin → Branding**
  (logo uploads are stored in `DATA_DIR/branding/`)

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

## Backups

While the app is running it snapshots the SQLite database into
`DATA_DIR/backups/` (the `ttks_data` volume in Docker) once a day at
`BACKUP_HOUR` (`HH:MM`, local time; default `03:00`), keeping the newest
`BACKUP_KEEP` files (default `7`). Admins can trigger a snapshot and download
backup files from the **Backups** admin page (`/admin/backup`).

**Download those files off the machine — backups living in the same volume as
the live database are not off-box protection.** Copy them to another host,
object storage, or removable media on a regular basis.

To restore a backup (Docker):

```sh
docker compose stop web
docker compose run --rm --entrypoint flask web restore-backup /data/backups/<file>
docker compose start web
```

`flask restore-backup` refuses to restore the live database over itself, runs
`PRAGMA integrity_check` on the backup first, keeps a safety copy of the
current database as `DATA_DIR/pre-restore-<UTCtimestamp>.db`, swaps the backup
in, and deletes stale `-wal`/`-shm` sidecar files.

## Environment variables

Pinned in `.env.example` and read by `app/config.py`:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session/CSRF signing key — set a long random value |
| `DATA_DIR` | Where the SQLite DB and avatars live (default `./data`, `/data` in Docker) |
| `ADMIN_USERNAME` | Initial admin created by `flask seed-admin` |
| `ADMIN_PASSWORD` | Initial admin password (forced change on first login) |
| `BACKUP_HOUR` | Daily backup time as `HH:MM`, local (default `03:00`) |
| `BACKUP_KEEP` | How many backup files to keep in `DATA_DIR/backups` (default `7`) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional Google sign-in — the "Sign in with Google" button appears only when both are set. Google sign-in creates an active account immediately (no admin approval); password registration still requires approval. |

`FLASK_APP=wsgi:app` is also set there for the flask CLI (the Docker image sets
it itself).
