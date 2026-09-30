#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${PASSIT_MODE:-demo}" != demo ]; then
  echo 'This helper prepares local development. Use controlled migrations for production.' >&2
  exit 1
fi
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/passit-uv-cache}"
export UV_LINK_MODE=copy
uv sync --frozen --extra dev --python python3
npm --prefix frontend ci
.venv/bin/alembic upgrade head
.venv/bin/python -m passit.manage seed
