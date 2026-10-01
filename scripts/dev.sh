#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PASSIT_ORIGIN="${PASSIT_ORIGIN:-http://localhost:${PASSIT_WEB_PORT:-5173}}"
children=()
cleanup() {
  if [ "${#children[@]}" -gt 0 ]; then
    kill "${children[@]}" 2>/dev/null || true
    wait "${children[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
.venv/bin/uvicorn passit.api:app --host 127.0.0.1 --port "${PASSIT_API_PORT:-8000}" &
children+=("$!")
.venv/bin/python -m passit.worker &
children+=("$!")
# Launch Vite directly so its process, rather than npm's parent, receives shutdown signals.
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port "${PASSIT_WEB_PORT:-5173}" --strictPort) &
children+=("$!")
wait -n "${children[@]}"
