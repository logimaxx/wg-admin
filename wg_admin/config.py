from __future__ import annotations

import os
import secrets
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def _writable_state_dir() -> Path:
    system = Path("/var/lib/wg-admin")
    if os.geteuid() == 0:
        return system
    if system.exists() and os.access(system, os.W_OK):
        return system
    return Path.home() / ".local/share/wg-admin"


class Settings:
    def __init__(self) -> None:
        self.demo = _env_bool("WG_ADMIN_DEMO")
        root = Path(__file__).resolve().parent.parent
        default_config = root / "demo" / "wireguard" if self.demo else Path("/etc/wireguard")
        default_state = root / "demo" / "state" if self.demo else _writable_state_dir()
        self.config_dir = _env_path("WG_ADMIN_CONFIG_DIR", default_config)
        self.state_dir = _env_path("WG_ADMIN_STATE_DIR", default_state)
        self.host = os.environ.get("WG_ADMIN_HOST", "127.0.0.1")
        self.port = int(os.environ.get("WG_ADMIN_PORT", "8080"))
        self.session_secret_file = self.state_dir / "session.key"
        self.state_file = self.state_dir / "state.json"
        self.backup_dir = self.state_dir / "backups"

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except OSError:
            pass

    def session_secret(self) -> str:
        self.ensure_dirs()
        if self.session_secret_file.exists():
            return self.session_secret_file.read_text().strip()
        secret = secrets.token_hex(32)
        self.session_secret_file.write_text(secret + "\n")
        os.chmod(self.session_secret_file, 0o600)
        return secret


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> Settings:
    global _settings
    _settings = Settings()
    return _settings
