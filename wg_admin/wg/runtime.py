from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PeerRuntime:
    public_key: str
    endpoint: str = ""
    allowed_ips: str = ""
    latest_handshake: int = 0
    transfer_rx: int = 0
    transfer_tx: int = 0
    persistent_keepalive: int = 0


@dataclass
class InterfaceRuntime:
    name: str
    public_key: str = ""
    listen_port: str = ""
    up: bool = False
    peers: dict[str, PeerRuntime] = field(default_factory=dict)


@dataclass
class Runtime:
    interfaces: dict[str, InterfaceRuntime] = field(default_factory=dict)
    available: bool = False
    error: str = ""

    def for_interface(self, name: str) -> InterfaceRuntime:
        return self.interfaces.get(name, InterfaceRuntime(name=name))


def _iface_is_up(name: str) -> bool:
    return Path(f"/sys/class/net/{name}").exists()


def _run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def load_runtime(demo: bool = False) -> Runtime:
    if demo:
        return Runtime(available=False, error="demo")
    if shutil.which("wg") is None:
        return Runtime(available=False, error="wg not found")
    try:
        dump = _run(["wg", "show", "all", "dump"])
    except (OSError, subprocess.CalledProcessError) as exc:
        return Runtime(available=False, error=str(exc))

    runtime = Runtime(available=True)
    current: InterfaceRuntime | None = None
    for raw in dump.splitlines():
        parts = raw.split("\t")
        if len(parts) == 5:
            name, _private, public_key, listen_port, _fwmark = parts
            current = InterfaceRuntime(
                name=name,
                public_key=public_key,
                listen_port=listen_port if listen_port != "0" else "",
                up=_iface_is_up(name),
            )
            runtime.interfaces[name] = current
            continue
        if current is None or len(parts) < 8:
            continue
        public_key, _psk, endpoint, allowed_ips, handshake, rx, tx, keepalive = parts[:8]
        current.peers[public_key] = PeerRuntime(
            public_key=public_key,
            endpoint="" if endpoint == "(none)" else endpoint,
            allowed_ips=allowed_ips,
            latest_handshake=int(handshake or 0),
            transfer_rx=int(rx or 0),
            transfer_tx=int(tx or 0),
            persistent_keepalive=int(keepalive or 0),
        )
    return runtime


def syncconf(name: str, stripped: str) -> None:
    if not _iface_is_up(name):
        return
    if shutil.which("wg") is None:
        raise RuntimeError("wg is not installed; config was saved but not applied live")
    subprocess.run(
        ["wg", "syncconf", name, "/dev/stdin"],
        input=stripped,
        text=True,
        check=True,
        capture_output=True,
    )
