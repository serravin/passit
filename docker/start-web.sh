#!/bin/sh
set -eu

# Only these placeholders are substituted; Nginx's own $host/$uri variables stay intact.
export PASSIT_API_UPSTREAM="${PASSIT_API_UPSTREAM:-http://api:8000}"
export PASSIT_CONNECT_SOURCES="${PASSIT_CONNECT_SOURCES:-'self'}"
envsubst '${PASSIT_API_UPSTREAM} ${PASSIT_CONNECT_SOURCES}' \
    < /etc/nginx/passit.conf.template > /tmp/passit-nginx.conf
exec nginx -c /tmp/passit-nginx.conf "$@"
