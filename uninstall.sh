#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/wg-admin}"
SERVICE_NAME="wg-admin"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run uninstall.sh as root." >&2
  exit 1
fi

systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
rm -rf "${PREFIX}"

echo "Removed the wg-admin service and ${PREFIX}."
echo "WireGuard configs in /etc/wireguard were not touched."
echo "State remains in ${WG_ADMIN_STATE_DIR:-/var/lib/wg-admin} (delete it if you want a clean slate)."
