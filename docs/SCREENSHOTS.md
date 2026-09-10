# Screenshots

wg-admin managing interfaces already present in `/etc/wireguard`.

## Interfaces

Every `*.conf` on the host is listed in place. Status comes from `wg` when the interface is up.

![Dashboard listing inherited WireGuard interfaces](screenshots/dashboard.png)

## Peers

Open an interface to see peers, last handshake, and transfer. Filter or sort the list. Disable a peer to keep it in the file without leaving it live.

![Peer list for wg0 with live handshake and transfer](screenshots/interface.png)

## Add a peer

Generate a keypair on the server, or paste a public key the client already has. The next free IPv4 in the interface subnet is suggested automatically. After create, the QR and `.conf` open when the private key is stored here.

![Add peer dialog](screenshots/add-peer.png)

## Client QR

Peers created or rotated in the UI get a downloadable `.conf` and a QR code. Imported peers keep working; they just have no private key on the server.

![QR code for a new client](screenshots/qr.png)

## First run

On install, existing interface files are inherited. Set an admin password before the console is usable.

![First-run setup inheriting existing WireGuard configs](screenshots/setup.png)

Back to the [README](../README.md).
