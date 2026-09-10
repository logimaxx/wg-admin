from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from wg_admin.wg.parse import WG_QUICK_ONLY, WgConfig, render_wg_config


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def backup_config(path: Path, backup_dir: Path, keep: int = 20) -> Path | None:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"{path.name}.{stamp}"
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    existing = sorted(backup_dir.glob(f"{path.name}.*"), reverse=True)
    for stale in existing[keep:]:
        stale.unlink(missing_ok=True)
    return dest


def strip_runtime_config(config: WgConfig) -> str:
    """Keep only keys that `wg syncconf` understands."""
    lines = ["[Interface]"]
    for key, value in config.interface:
        if key.lower() in WG_QUICK_ONLY:
            continue
        lines.append(f"{key} = {value}")
    for peer in config.peers:
        if peer.disabled:
            continue
        lines.append("")
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
            if key.lower() not in WG_QUICK_ONLY:
                lines.append(f"{key} = {value}")
    lines.append("")
    return "\n".join(lines)


def apply_config(
    config: WgConfig,
    backup_dir: Path,
    sync: bool = True,
    run_sync=None,
) -> None:
    backup_config(config.path, backup_dir)
    atomic_write(config.path, render_wg_config(config))
    if sync and run_sync is not None:
        run_sync(config.name, strip_runtime_config(config))
