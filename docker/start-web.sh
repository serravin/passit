#!/bin/sh
set -eu

# Only these placeholders are substituted; Nginx's own $host/$uri variables stay intact.
export PASSIT_API_UPSTREAM="${PASSIT_API_UPSTREAM:-http://api:8000}"
export PASSIT_CONNECT_SOURCES="${PASSIT_CONNECT_SOURCES:-'self'}"
envsubst '${PASSIT_API_UPSTREAM} ${PASSIT_CONNECT_SOURCES}' \
    < /etc/nginx/passit.conf.template > /tmp/passit-nginx.conf
# Public browser settings are runtime data, allowing one image in multiple environments.
awk 'function quote(value) {
    if (value ~ /[[:cntrl:]]/) exit 1;
    gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value);
    return "\"" value "\"";
}
BEGIN {
    printf "{\"authority\":%s,\"clientId\":%s,\"scope\":%s}\n",
        quote(ENVIRON["VITE_OIDC_AUTHORITY"]), quote(ENVIRON["VITE_OIDC_CLIENT_ID"]),
        quote(ENVIRON["VITE_OIDC_SCOPE"]);
}' > /tmp/passit-runtime-config.json
exec nginx -c /tmp/passit-nginx.conf "$@"
