#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/wg-admin}"
STATE_DIR="${WG_ADMIN_STATE_DIR:-/var/lib/wg-admin}"
CONFIG_DIR="${WG_ADMIN_CONFIG_DIR:-/etc/wireguard}"
ENV_FILE="${WG_ADMIN_ENV:-/etc/wg-admin.env}"
SERVICE_NAME="wg-admin"
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run install.sh as root so it can read ${CONFIG_DIR} and install the service." >&2
  exit 1
fi

if ! command -v python3 >/dev/null; then
  echo "python3 is required." >&2
  exit 1
fi

PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [[ "$(python3 -c 'import sys; print(sys.version_info.major)')" -lt 3 || "${PY_MINOR}" -lt 11 ]]; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if ! command -v wg >/dev/null; then
  echo "warning: wg is not on PATH. Config files can still be edited; live sync needs wireguard-tools." >&2
fi

mkdir -p "${PREFIX}" "${STATE_DIR}" "${STATE_DIR}/backups"
chmod 700 "${STATE_DIR}"

if command -v rsync >/dev/null; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude 'demo/state' \
    --exclude 'venv' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "${SRC}/" "${PREFIX}/"
else
  mkdir -p "${PREFIX}"
  find "${PREFIX}" -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf {} +
  cp -a "${SRC}/." "${PREFIX}/"
  rm -rf "${PREFIX}/.git" "${PREFIX}/demo/state"
fi

python3 -m venv "${PREFIX}/venv"
"${PREFIX}/venv/bin/pip" install --upgrade pip
"${PREFIX}/venv/bin/pip" install "${PREFIX}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<EOF
WG_ADMIN_HOST=127.0.0.1
WG_ADMIN_PORT=8080
WG_ADMIN_CONFIG_DIR=${CONFIG_DIR}
WG_ADMIN_STATE_DIR=${STATE_DIR}
EOF
  chmod 600 "${ENV_FILE}"
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=WireGuard admin web UI
After=network.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${PREFIX}
ExecStart=${PREFIX}/venv/bin/wg-admin
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"

HOST="$(grep '^WG_ADMIN_HOST=' "${ENV_FILE}" | cut -d= -f2)"
PORT="$(grep '^WG_ADMIN_PORT=' "${ENV_FILE}" | cut -d= -f2)"

echo
echo "wg-admin is installed."
echo "  UI:      http://${HOST}:${PORT}"
echo "  Configs: ${CONFIG_DIR} (existing *.conf files are inherited)"
echo "  State:   ${STATE_DIR}"
echo
echo "Open the URL and set an admin password. Keep the service on localhost"
echo "and put TLS in front if you expose it beyond this host."
