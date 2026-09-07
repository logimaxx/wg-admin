from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@dataclass
class PeerMeta:
    name: str = ""
    private_key: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {"name": self.name, "notes": self.notes}
        if self.private_key:
            data["private_key"] = self.private_key
        return data


@dataclass
class InterfaceMeta:
    client_dns: str = "1.1.1.1"
    client_allowed_ips: str = "0.0.0.0/0, ::/0"
    endpoint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "client_dns": self.client_dns,
            "client_allowed_ips": self.client_allowed_ips,
            "endpoint": self.endpoint,
        }


@dataclass
class AppState:
    path: Path
    password_hash: str = ""
    peer_meta: dict[str, dict[str, PeerMeta]] = field(default_factory=dict)
    interface_meta: dict[str, InterfaceMeta] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> AppState:
        raw = _load(path)
        state = cls(path=path, password_hash=str(raw.get("password_hash", "")))
        for iface, peers in (raw.get("peer_meta") or {}).items():
            state.peer_meta[iface] = {
                pubkey: PeerMeta(
                    name=str(meta.get("name", "")),
                    private_key=str(meta.get("private_key", "")),
                    notes=str(meta.get("notes", "")),
                )
                for pubkey, meta in peers.items()
            }
        for iface, meta in (raw.get("interface_meta") or {}).items():
            state.interface_meta[iface] = InterfaceMeta(
                client_dns=str(meta.get("client_dns", "1.1.1.1")),
                client_allowed_ips=str(meta.get("client_allowed_ips", "0.0.0.0/0, ::/0")),
                endpoint=str(meta.get("endpoint", "")),
            )
        return state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "password_hash": self.password_hash,
            "peer_meta": {
                iface: {pubkey: meta.to_dict() for pubkey, meta in peers.items()}
                for iface, peers in self.peer_meta.items()
            },
            "interface_meta": {iface: meta.to_dict() for iface, meta in self.interface_meta.items()},
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def peer(self, iface: str, public_key: str) -> PeerMeta:
        return self.peer_meta.setdefault(iface, {}).setdefault(public_key, PeerMeta())

    def interface(self, iface: str) -> InterfaceMeta:
        return self.interface_meta.setdefault(iface, InterfaceMeta())

    def rename_peer(self, iface: str, old_key: str, new_key: str) -> None:
        peers = self.peer_meta.get(iface) or {}
        meta = peers.pop(old_key, None)
        if meta is not None:
            peers[new_key] = meta
            self.peer_meta[iface] = peers

    def drop_peer(self, iface: str, public_key: str) -> None:
        peers = self.peer_meta.get(iface) or {}
        peers.pop(public_key, None)
