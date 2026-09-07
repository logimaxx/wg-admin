from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


WG_QUICK_ONLY = {
    "address",
    "dns",
    "mtu",
    "table",
    "preup",
    "postup",
    "predown",
    "postdown",
    "saveconfig",
}


@dataclass
class WgPeer:
    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    preshared_key: str | None = None
    persistent_keepalive: int | None = None
    endpoint: str | None = None
    extra: list[tuple[str, str]] = field(default_factory=list)
    name: str = ""
    comments: list[str] = field(default_factory=list)

    def allowed_ips_csv(self) -> str:
        return ", ".join(self.allowed_ips)


@dataclass
class WgConfig:
    name: str
    path: Path
    interface: list[tuple[str, str]] = field(default_factory=list)
    peers: list[WgPeer] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)

    def interface_values(self, key: str) -> list[str]:
        needle = key.lower()
        return [value for item, value in self.interface if item.lower() == needle]

    def interface_value(self, key: str, default: str = "") -> str:
        values = self.interface_values(key)
        return values[0] if values else default

    def set_interface_value(self, key: str, value: str) -> None:
        for index, (item, _) in enumerate(self.interface):
            if item.lower() == key.lower():
                self.interface[index] = (item, value)
                return
        self.interface.append((key, value))

    def private_key(self) -> str:
        return self.interface_value("PrivateKey")

    def addresses(self) -> list[str]:
        found: list[str] = []
        for value in self.interface_values("Address"):
            found.extend(part.strip() for part in value.split(",") if part.strip())
        return found

    def listen_port(self) -> str:
        return self.interface_value("ListenPort")

    def peer_by_public_key(self, public_key: str) -> WgPeer | None:
        for peer in self.peers:
            if peer.public_key == public_key:
                return peer
        return None

    def replace_peer(self, public_key: str, peer: WgPeer) -> None:
        for index, existing in enumerate(self.peers):
            if existing.public_key == public_key:
                self.peers[index] = peer
                return
        self.peers.append(peer)

    def remove_peer(self, public_key: str) -> bool:
        before = len(self.peers)
        self.peers = [peer for peer in self.peers if peer.public_key != public_key]
        return len(self.peers) != before


def _split_comment(value: str) -> str:
    if " #" in value:
        return value.split(" #", 1)[0].strip()
    return value.strip()


def _comment_name(comments: list[str]) -> str:
    for line in reversed(comments):
        text = line.lstrip("#").strip()
        if not text:
            continue
        if text.lower().startswith("name"):
            _, _, rest = text.partition("=")
            return rest.strip() or text
        return text
    return ""


def _peer_from_pairs(pairs: list[tuple[str, str]], comments: list[str]) -> WgPeer:
    peer = WgPeer(public_key="", comments=list(comments), name=_comment_name(comments))
    for key, value in pairs:
        lowered = key.lower()
        if lowered == "publickey":
            peer.public_key = value
        elif lowered == "allowedips":
            peer.allowed_ips.extend(part.strip() for part in value.split(",") if part.strip())
        elif lowered == "presharedkey":
            peer.preshared_key = value
        elif lowered == "persistentkeepalive":
            peer.persistent_keepalive = int(value) if value else None
        elif lowered == "endpoint":
            peer.endpoint = value
        else:
            peer.extra.append((key, value))
    return peer


def parse_wg_config(path: Path, name: str | None = None) -> WgConfig:
    text = path.read_text(encoding="utf-8")
    config = WgConfig(name=name or path.stem, path=path)
    section: str | None = None
    pending_comments: list[str] = []
    peer_comments: list[str] = []
    peer_pairs: list[tuple[str, str]] = []

    def flush_peer() -> None:
        nonlocal peer_pairs, peer_comments
        if section == "peer":
            peer = _peer_from_pairs(peer_pairs, peer_comments)
            if peer.public_key:
                config.peers.append(peer)
        peer_pairs = []
        peer_comments = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if section is None:
                config.preamble.append(raw_line)
            continue
        if stripped.startswith("#") or stripped.startswith(";"):
            if section is None:
                config.preamble.append(raw_line)
            elif section == "peer" and not peer_pairs:
                peer_comments.append(stripped)
            else:
                pending_comments.append(stripped)
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            label = stripped[1:-1].strip().lower()
            if label == "interface":
                flush_peer()
                section = "interface"
            elif label == "peer":
                flush_peer()
                section = "peer"
                peer_comments = pending_comments
                pending_comments = []
            else:
                flush_peer()
                section = label
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), _split_comment(value)
        if section == "interface":
            config.interface.append((key, value))
        elif section == "peer":
            peer_pairs.append((key, value))

    flush_peer()
    return config


def render_wg_config(config: WgConfig) -> str:
    lines: list[str] = []
    if config.preamble:
        lines.extend(config.preamble)
        if config.preamble[-1].strip():
            lines.append("")
    lines.append("[Interface]")
    for key, value in config.interface:
        lines.append(f"{key} = {value}")
    for peer in config.peers:
        lines.append("")
        if peer.name:
            lines.append(f"# {peer.name}")
        elif peer.comments:
            lines.extend(peer.comments)
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        if peer.allowed_ips:
            lines.append(f"AllowedIPs = {peer.allowed_ips_csv()}")
        if peer.endpoint:
            lines.append(f"Endpoint = {peer.endpoint}")
        if peer.persistent_keepalive is not None:
            lines.append(f"PersistentKeepalive = {peer.persistent_keepalive}")
        for key, value in peer.extra:
            lines.append(f"{key} = {value}")
    lines.append("")
    return "\n".join(lines)


def load_configs(config_dir: Path) -> list[WgConfig]:
    if not config_dir.exists():
        return []
    configs: list[WgConfig] = []
    for path in sorted(config_dir.glob("*.conf")):
        if path.name.endswith(".conf.tmp"):
            continue
        configs.append(parse_wg_config(path))
    return configs
