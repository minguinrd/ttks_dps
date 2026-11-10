#!/bin/sh
set -e

flask db upgrade
flask seed-admin
exec gunicorn -w 2 -b 0.0.0.0:8000 wsgi:app
