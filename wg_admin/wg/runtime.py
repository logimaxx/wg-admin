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


def _dump_int(value: str) -> int:
    if not value or value in {"off", "(none)"}:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def parse_wg_dump(dump: str, iface_is_up=_iface_is_up) -> Runtime:
    """Parse `wg show all dump` (and single-iface `wg show dump`).

    With `all`, every row is prefixed with the interface name, so peer rows
    have 9 columns. Without it, peer rows have 8.
    """
    runtime = Runtime(available=True)
    current: InterfaceRuntime | None = None
    for raw in dump.splitlines():
        parts = raw.split("\t")
        if len(parts) == 5:
            name, _private, public_key, listen_port, _fwmark = parts
            current = InterfaceRuntime(
                name=name,
                public_key=public_key,
                listen_port="" if listen_port in {"0", "off"} else listen_port,
                up=iface_is_up(name),
            )
            runtime.interfaces[name] = current
            continue
        if len(parts) >= 9:
            name, public_key, _psk, endpoint, allowed_ips, handshake, rx, tx, keepalive = parts[:9]
            current = runtime.interfaces.get(name, current)
        elif len(parts) >= 8:
            public_key, _psk, endpoint, allowed_ips, handshake, rx, tx, keepalive = parts[:8]
        else:
            continue
        if current is None:
            continue
        current.peers[public_key] = PeerRuntime(
            public_key=public_key,
            endpoint="" if endpoint in {"", "(none)"} else endpoint,
            allowed_ips="" if allowed_ips == "(none)" else allowed_ips,
            latest_handshake=_dump_int(handshake),
            transfer_rx=_dump_int(rx),
            transfer_tx=_dump_int(tx),
            persistent_keepalive=_dump_int(keepalive),
        )
    return runtime


def load_runtime(demo: bool = False) -> Runtime:
    if demo:
        return Runtime(available=False, error="demo")
    if shutil.which("wg") is None:
        return Runtime(available=False, error="wg not found")
    try:
        dump = _run(["wg", "show", "all", "dump"])
        return parse_wg_dump(dump)
    except (OSError, subprocess.CalledProcessError) as exc:
        return Runtime(available=False, error=str(exc))


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


def bounce(name: str) -> None:
    if shutil.which("wg-quick") is None:
        raise RuntimeError("wg-quick is not installed; the interface was not restarted")
    subprocess.run(["wg-quick", "down", name], capture_output=True, text=True)
    up = subprocess.run(["wg-quick", "up", name], capture_output=True, text=True)
    if up.returncode != 0:
        detail = (up.stderr or up.stdout or "wg-quick up failed").strip()
        raise RuntimeError(detail)
