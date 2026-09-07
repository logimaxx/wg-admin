#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export WG_ADMIN_DEMO=1
export WG_ADMIN_CONFIG_DIR="${ROOT}/demo/wireguard"
export WG_ADMIN_STATE_DIR="${ROOT}/demo/state"
export WG_ADMIN_HOST="${WG_ADMIN_HOST:-127.0.0.1}"
export WG_ADMIN_PORT="${WG_ADMIN_PORT:-8080}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  exec "${ROOT}/.venv/bin/python" -m wg_admin
fi
exec python3 -m wg_admin
