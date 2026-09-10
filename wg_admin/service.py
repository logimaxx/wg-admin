from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import bcrypt
import qrcode

from wg_admin.config import Settings
from wg_admin.state import AppState, InterfaceMeta, PeerMeta
from wg_admin.wg.ips import next_ipv4
from wg_admin.wg.keys import genkey, genpsk, pubkey, require_key
from wg_admin.wg.parse import WgConfig, WgPeer, load_configs, parse_wg_config, render_wg_config
from wg_admin.wg.runtime import Runtime, bounce, load_runtime, syncconf
from wg_admin.wg.write import apply_config


QUICK_HOOK_KEYS = ("Address", "DNS", "MTU", "Table", "PreUp", "PostUp", "PreDown", "PostDown")
BACKUP_STAMP = re.compile(r"^\d{8}-\d{6}$")


def _split_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _split_csv(raw: str) -> list[str]:
    parts: list[str] = []
    for line in raw.replace(",", "\n").splitlines():
        item = line.strip()
        if item:
            parts.append(item)
    return parts


def _quick_snapshot(config: WgConfig) -> dict[str, tuple[str, ...]]:
    return {key: tuple(config.interface_values(key)) for key in QUICK_HOOK_KEYS}


def safe_pubkey(private_key: str) -> str:
    if not private_key:
        return ""
    try:
        return pubkey(private_key)
    except ValueError:
        return ""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def handshake_age(ts: int) -> str:
    if not ts:
        return "never"
    now = int(datetime.now(timezone.utc).timestamp())
    delta = max(0, now - ts)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def handshake_class(ts: int) -> str:
    if not ts:
        return "led-off"
    now = int(datetime.now(timezone.utc).timestamp())
    delta = max(0, now - ts)
    if delta < 180:
        return "led-ok"
    if delta < 7200:
        return "led-warn"
    return "led-off"


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit, size in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)):
        if n < size * 1024:
            value = n / size
            return f"{value:.1f} {unit}"
    return f"{n} B"


@dataclass
class PeerView:
    name: str
    public_key: str
    allowed_ips: str
    keepalive: str
    has_private_key: bool
    handshake: str
    handshake_class: str
    handshake_ts: int
    transfer: str
    transfer_bytes: int
    endpoint: str
    encoded_key: str
    notes: str
    disabled: bool
    client_dns: str
    client_allowed_ips: str
    client_endpoint: str


@dataclass
class BackupView:
    stamp: str
    label: str
    size: str


@dataclass
class InterfaceView:
    name: str
    up: bool
    addresses: str
    listen_port: str
    public_key: str
    peer_count: int
    last_handshake: str
    raw: str
    settings: InterfaceMeta
    next_ip: str
    peers: list[PeerView]
    suggested_endpoint: str
    backups: list[BackupView]
    mtu: str
    dns: str
    table: str
    postup: str
    postdown: str
    preup: str
    predown: str


class Manager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.state = AppState.load(settings.state_file)

    def reload_state(self) -> None:
        self.state = AppState.load(self.settings.state_file)

    def configs(self) -> list[WgConfig]:
        return load_configs(self.settings.config_dir)

    def config(self, name: str) -> WgConfig:
        path = (self.settings.config_dir / f"{name}.conf").resolve()
        if path.parent != self.settings.config_dir.resolve() or not path.is_file():
            raise FileNotFoundError(name)
        return parse_wg_config(path, name=name)

    def runtime(self) -> Runtime:
        return load_runtime(demo=self.settings.demo)

    def inherit_names(self) -> None:
        changed = False
        for config in self.configs():
            for peer in config.peers:
                meta = self.state.peer(config.name, peer.public_key)
                if peer.name and not meta.name:
                    meta.name = peer.name
                    changed = True
        if changed:
            self.state.save()

    def setup_password(self, password: str) -> None:
        self.state.password_hash = hash_password(password)
        self.state.save()

    def change_password(self, current: str, new_password: str) -> None:
        if not check_password(current, self.state.password_hash):
            raise ValueError("Current password is wrong")
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self.state.password_hash = hash_password(new_password)
        self.state.save()

    def apply(self, config: WgConfig) -> None:
        def run_sync(name: str, stripped: str) -> None:
            if self.settings.demo:
                return
            syncconf(name, stripped)

        apply_config(
            config,
            backup_dir=self.settings.backup_dir,
            sync=not self.settings.demo,
            run_sync=run_sync,
        )
        self.state.save()

    def interface_view(self, name: str, host_hint: str = "") -> InterfaceView:
        config = self.config(name)
        runtime = self.runtime().for_interface(name)
        settings = self.state.interface(name)
        public_key = runtime.public_key or safe_pubkey(config.private_key())
        try:
            suggested_ip = next_ipv4(config)
        except ValueError:
            suggested_ip = ""
        peers: list[PeerView] = []
        latest = 0
        for peer in config.peers:
            live = runtime.peers.get(peer.public_key)
            meta = self.state.peer(name, peer.public_key)
            display = meta.name or peer.name or peer.public_key[:8]
            handshake_ts = live.latest_handshake if live else 0
            latest = max(latest, handshake_ts)
            rx = live.transfer_rx if live else 0
            tx = live.transfer_tx if live else 0
            if peer.disabled:
                handshake = "disabled"
                handshake_css = "led-off"
                transfer = "—"
                endpoint = "—"
            else:
                handshake = handshake_age(handshake_ts)
                handshake_css = handshake_class(handshake_ts)
                transfer = f"{format_bytes(rx)} in / {format_bytes(tx)} out" if live else "—"
                endpoint = (live.endpoint if live and live.endpoint else peer.endpoint) or "—"
            peers.append(
                PeerView(
                    name=display,
                    public_key=peer.public_key,
                    allowed_ips=peer.allowed_ips_csv(),
                    keepalive="" if peer.persistent_keepalive is None else str(peer.persistent_keepalive),
                    has_private_key=bool(meta.private_key),
                    handshake=handshake,
                    handshake_class=handshake_css,
                    handshake_ts=0 if peer.disabled else handshake_ts,
                    transfer=transfer,
                    transfer_bytes=0 if peer.disabled else rx + tx,
                    endpoint=endpoint,
                    encoded_key=encode_peer_id(peer.public_key),
                    notes=meta.notes,
                    disabled=peer.disabled,
                    client_dns=meta.client_dns,
                    client_allowed_ips=meta.client_allowed_ips,
                    client_endpoint=meta.client_endpoint,
                )
            )
        endpoint = settings.endpoint
        if not endpoint and host_hint and config.listen_port():
            endpoint = f"{host_hint}:{config.listen_port()}"
        up = runtime.up
        if self.settings.demo:
            up = True
        return InterfaceView(
            name=name,
            up=up,
            addresses=", ".join(config.addresses()) or "—",
            listen_port=config.listen_port() or runtime.listen_port or "—",
            public_key=public_key,
            peer_count=len(config.peers),
            last_handshake=handshake_age(latest) if latest else "never",
            raw=render_wg_config(config),
            settings=settings,
            next_ip=suggested_ip,
            peers=peers,
            suggested_endpoint=endpoint,
            backups=self.backups(name),
            mtu=config.interface_value("MTU"),
            dns=", ".join(config.interface_values("DNS")),
            table=config.interface_value("Table"),
            postup="\n".join(config.interface_values("PostUp")),
            postdown="\n".join(config.interface_values("PostDown")),
            preup="\n".join(config.interface_values("PreUp")),
            predown="\n".join(config.interface_values("PreDown")),
        )

    def dashboard(self, host_hint: str = "") -> list[InterfaceView]:
        self.inherit_names()
        return [self.interface_view(cfg.name, host_hint=host_hint) for cfg in self.configs()]

    def add_peer(
        self,
        name: str,
        peer_name: str,
        allowed_ips: str,
        keepalive: str,
        notes: str = "",
        use_psk: bool = True,
        public_key: str = "",
        preshared_key: str = "",
        client_dns: str = "",
        client_allowed_ips: str = "",
        client_endpoint: str = "",
    ) -> WgPeer:
        config = self.config(name)
        existing = public_key.strip()
        if existing:
            existing = require_key(existing, "public key")
            if config.peer_by_public_key(existing):
                raise ValueError("A peer with this public key already exists")
            private_key = ""
            public_key = existing
        else:
            private_key = genkey()
            public_key = pubkey(private_key)
        ips = [part.strip() for part in allowed_ips.split(",") if part.strip()]
        if not ips:
            ips = [next_ipv4(config)]
        psk = preshared_key.strip()
        if psk:
            psk = require_key(psk, "preshared key")
        elif use_psk:
            psk = genpsk()
        else:
            psk = None
        peer = WgPeer(
            public_key=public_key,
            allowed_ips=ips,
            preshared_key=psk,
            persistent_keepalive=int(keepalive) if keepalive.strip() else 25,
            name=peer_name.strip() or public_key[:8],
        )
        config.peers.append(peer)
        meta = self.state.peer(name, public_key)
        meta.name = peer.name
        meta.private_key = private_key
        meta.notes = notes.strip()
        self._store_client_overrides(meta, client_dns, client_allowed_ips, client_endpoint)
        self.apply(config)
        return peer

    def _store_client_overrides(
        self,
        meta: PeerMeta,
        client_dns: str,
        client_allowed_ips: str,
        client_endpoint: str,
    ) -> None:
        meta.client_dns = client_dns.strip()
        meta.client_allowed_ips = client_allowed_ips.strip()
        meta.client_endpoint = client_endpoint.strip()

    def edit_peer(
        self,
        name: str,
        public_key: str,
        peer_name: str,
        allowed_ips: str,
        keepalive: str,
        notes: str = "",
        client_dns: str = "",
        client_allowed_ips: str = "",
        client_endpoint: str = "",
    ) -> None:
        config = self.config(name)
        peer = config.peer_by_public_key(public_key)
        if peer is None:
            raise FileNotFoundError(public_key)
        peer.name = peer_name.strip() or peer.name
        peer.allowed_ips = [part.strip() for part in allowed_ips.split(",") if part.strip()]
        peer.persistent_keepalive = int(keepalive) if keepalive.strip() else None
        meta = self.state.peer(name, public_key)
        meta.name = peer.name
        meta.notes = notes.strip()
        self._store_client_overrides(meta, client_dns, client_allowed_ips, client_endpoint)
        self.apply(config)

    def set_peer_disabled(self, name: str, public_key: str, disabled: bool) -> WgPeer:
        config = self.config(name)
        peer = config.peer_by_public_key(public_key)
        if peer is None:
            raise FileNotFoundError(public_key)
        peer.disabled = disabled
        self.apply(config)
        return peer

    def delete_peer(self, name: str, public_key: str) -> None:
        config = self.config(name)
        if not config.remove_peer(public_key):
            raise FileNotFoundError(public_key)
        self.state.drop_peer(name, public_key)
        self.apply(config)

    def rotate_peer(self, name: str, public_key: str) -> WgPeer:
        config = self.config(name)
        peer = config.peer_by_public_key(public_key)
        if peer is None:
            raise FileNotFoundError(public_key)
        old = self.state.peer(name, public_key)
        private_key = genkey()
        new_pub = pubkey(private_key)
        peer.public_key = new_pub
        peer.preshared_key = genpsk()
        self.state.rename_peer(name, public_key, new_pub)
        meta = self.state.peer(name, new_pub)
        meta.name = old.name or peer.name
        meta.notes = old.notes
        meta.private_key = private_key
        peer.name = meta.name
        self.apply(config)
        return peer

    def save_interface_settings(
        self,
        name: str,
        endpoint: str,
        client_dns: str,
        client_allowed_ips: str,
    ) -> None:
        meta = self.state.interface(name)
        meta.endpoint = endpoint.strip()
        meta.client_dns = client_dns.strip() or "1.1.1.1"
        meta.client_allowed_ips = client_allowed_ips.strip() or "0.0.0.0/0, ::/0"
        self.state.save()

    def save_server_interface(
        self,
        name: str,
        address: str,
        listen_port: str,
        mtu: str = "",
        dns: str = "",
        table: str = "",
        postup: str = "",
        postdown: str = "",
        preup: str = "",
        predown: str = "",
    ) -> bool:
        config = self.config(name)
        addresses = _split_csv(address)
        if not addresses:
            raise ValueError("Interface Address is required")
        before = _quick_snapshot(config)
        config.set_interface_values("Address", addresses)
        config.set_interface_values("ListenPort", [listen_port])
        config.set_interface_values("MTU", [mtu])
        config.set_interface_values("DNS", _split_csv(dns))
        config.set_interface_values("Table", [table])
        config.set_interface_values("PostUp", _split_lines(postup))
        config.set_interface_values("PostDown", _split_lines(postdown))
        config.set_interface_values("PreUp", _split_lines(preup))
        config.set_interface_values("PreDown", _split_lines(predown))
        if not config.private_key():
            raise ValueError("Refusing to save an interface without PrivateKey")
        changed = _quick_snapshot(config) != before
        self.apply(config)
        return changed

    def bounce_interface(self, name: str) -> None:
        self.config(name)
        if self.settings.demo:
            return
        bounce(name)

    def backups(self, name: str) -> list[BackupView]:
        prefix = f"{name}.conf."
        items: list[BackupView] = []
        for path in sorted(self.settings.backup_dir.glob(f"{name}.conf.*"), reverse=True):
            stamp = path.name[len(prefix) :]
            if not BACKUP_STAMP.match(stamp):
                continue
            try:
                parsed = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
                label = parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
            except ValueError:
                label = stamp
            items.append(BackupView(stamp=stamp, label=label, size=format_bytes(path.stat().st_size)))
        return items

    def restore_backup(self, name: str, stamp: str) -> None:
        if not BACKUP_STAMP.match(stamp):
            raise FileNotFoundError(stamp)
        backup_dir = self.settings.backup_dir.resolve()
        src = (self.settings.backup_dir / f"{name}.conf.{stamp}").resolve()
        if src.parent != backup_dir or not src.is_file():
            raise FileNotFoundError(stamp)
        live = self.config(name)
        restored = parse_wg_config(src, name=name)
        restored.path = live.path
        self.apply(restored)

    def client_config(self, name: str, public_key: str) -> str:
        config = self.config(name)
        peer = config.peer_by_public_key(public_key)
        if peer is None:
            raise FileNotFoundError(public_key)
        meta = self.state.peer(name, public_key)
        if not meta.private_key:
            raise ValueError("Imported peer has no stored private key")
        iface = self.state.interface(name)
        server_pub = safe_pubkey(config.private_key())
        address = peer.allowed_ips[0] if peer.allowed_ips else ""
        dns = meta.client_dns or iface.client_dns
        endpoint = meta.client_endpoint or iface.endpoint
        allowed = meta.client_allowed_ips or iface.client_allowed_ips
        lines = [
            f"# {meta.name or peer.name or name}",
            "[Interface]",
            f"PrivateKey = {meta.private_key}",
            f"Address = {address}",
        ]
        if dns:
            lines.append(f"DNS = {dns}")
        lines.extend(
            [
                "",
                "[Peer]",
                f"PublicKey = {server_pub}",
            ]
        )
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        if endpoint:
            lines.append(f"Endpoint = {endpoint}")
        lines.append(f"AllowedIPs = {allowed}")
        if peer.persistent_keepalive is not None:
            lines.append(f"PersistentKeepalive = {peer.persistent_keepalive}")
        lines.append("")
        return "\n".join(lines)

    def client_qr_png(self, name: str, public_key: str) -> bytes:
        text = self.client_config(name, public_key)
        image = qrcode.make(text)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


def safe_name(name: str) -> str:
    if not name or "/" in name or name.startswith(".") or not name.replace("_", "").replace("-", "").isalnum():
        raise FileNotFoundError(name)
    return name


def encode_peer_id(public_key: str) -> str:
    return public_key.replace("+", "-").replace("/", "_").rstrip("=")


def decode_peer_id(peer_id: str) -> str:
    padded = peer_id.replace("-", "+").replace("_", "/")
    pad = (4 - len(padded) % 4) % 4
    return padded + ("=" * pad)
