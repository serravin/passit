#!/usr/bin/env bash
set -euo pipefail

image=${1:?Usage: bash scripts/web_smoke.sh IMAGE}
container=web-smoke

cleanup() {
    status=$?
    trap - EXIT
    if (( status != 0 )); then
        docker inspect --format '{{json .State}}' "$container" || true
        docker logs --tail 100 "$container" || true
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT

docker run --detach --name "$container" --publish 127.0.0.1:8080:8080 \
    --read-only --tmpfs /tmp:size=32m,mode=1777 --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --env VITE_OIDC_AUTHORITY=https://tenant.example.test/tenant/v2.0 \
    --env VITE_OIDC_CLIENT_ID=smoke-client \
    --env "VITE_OIDC_SCOPE=openid api://smoke/play" \
    --env PASSIT_API_UPSTREAM=http://127.0.0.1:8000 \
    --env "PASSIT_CONNECT_SOURCES='self' https://tenant.example.test" \
    "$image"

# Docker can publish the port before Nginx is listening. Retry failed health probes,
# including connection resets, but stop immediately if the container has exited.
ready=false
for attempt in {1..30}; do
    if [[ $(docker inspect --format '{{.State.Running}}' "$container") != true ]]; then
        echo 'Web container exited before becoming ready' >&2
        exit 1
    fi
    if curl --fail --silent --show-error --connect-timeout 1 --max-time 2 \
        http://127.0.0.1:8080/healthz >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
if [[ $ready != true ]]; then
    echo 'Web container did not become ready after 30 health probes' >&2
    exit 1
fi

curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/auth/callback \
    | python -c 'import sys; assert "<div id=\"root\">" in sys.stdin.read()'
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/runtime-config.json \
    | python -c 'import json,sys; c=json.load(sys.stdin); assert c["clientId"] == "smoke-client" and c["scope"] == "openid api://smoke/play"'
