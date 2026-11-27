#!/bin/sh
set -eu

flask db upgrade
flask seed-admin
# exec: gunicorn becomes PID 1 and receives SIGTERM from `docker stop`.
exec gunicorn --config gunicorn.conf.py wsgi:app
