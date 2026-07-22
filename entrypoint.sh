#!/bin/sh
# container entry point
set -eu

python manage.py migrate --noinput

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
    python manage.py seed_demo_data
fi

exec "$@"