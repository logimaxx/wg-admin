# wg-admin

A small web UI you install on a host that already runs WireGuard. It reads the existing files in `/etc/wireguard`, lets you add and edit peers, and applies changes with `wg syncconf` so the interface does not bounce.

It does not install WireGuard, replace `wg-quick`, or rewrite your `PostUp` / NAT lines.

## Install on a running VPN

```bash
sudo ./install.sh
```

Then open `http://127.0.0.1:8080` and set an admin password. Every `*.conf` already in `/etc/wireguard` is listed and managed in place.

Before the first write, a copy of the file is stored under `/var/lib/wg-admin/backups/`.

Defaults live in `/etc/wg-admin.env`:

```
WG_ADMIN_HOST=127.0.0.1
WG_ADMIN_PORT=8080
WG_ADMIN_CONFIG_DIR=/etc/wireguard
WG_ADMIN_STATE_DIR=/var/lib/wg-admin
```

Keep the service on localhost. Put Caddy or nginx with TLS in front if anyone else needs access.

```bash
sudo ./uninstall.sh   # removes the service; leaves WireGuard configs alone
```

## What it inherits

| From the server `.conf` | Kept as-is |
|---|---|
| `[Interface]` keys (`Address`, `ListenPort`, `PrivateKey`, `PostUp` / `PostDown`, `MTU`, `Table`, `DNS`, …) | Yes |
| Existing `[Peer]` public keys, AllowedIPs, PSK, keepalive, endpoint | Yes |
| Comment above a peer (`# Alice` or `# Name = Alice`) | Used as the display name |

WireGuard never stores a client private key on the server. Peers that already existed can be edited and removed, but a downloadable `.conf` / QR code is only available for peers created (or rotated) in this UI.

Client-only settings (public endpoint, DNS, client AllowedIPs) are stored in `/var/lib/wg-admin/state.json`, not in the server config.

## Daily use

- Open an interface to see peers, last handshake, and transfer.
- **Add peer** generates keys, picks the next free IPv4 in the interface subnet, and writes the server file.
- Download the client file or scan the QR code.
- Save / apply uses `wg syncconf` when the interface is up. If it is down, only the file is updated.

## Develop / demo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
./scripts/run-demo.sh
```

Demo mode uses `demo/wireguard` and never calls `wg`.

## Requirements

- Linux with Python 3.11+
- `wireguard-tools` (`wg`) for live status and apply
- Root (or equivalent access to `/etc/wireguard` and `CAP_NET_ADMIN`)
