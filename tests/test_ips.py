from pathlib import Path

from wg_admin.wg.ips import next_ipv4, used_ipv4s
from wg_admin.wg.parse import parse_wg_config


def _cfg(tmp_path: Path, extra_peers: str = "") -> Path:
    path = tmp_path / "wg0.conf"
    path.write_text(
        f"""[Interface]
PrivateKey = {"A" * 43}=
Address = 10.8.0.1/24
ListenPort = 51820

[Peer]
PublicKey = {"B" * 43}=
AllowedIPs = 10.8.0.2/32
{extra_peers}
""",
        encoding="utf-8",
    )
    return path


def test_next_ip_skips_server_and_peers(tmp_path: Path):
    cfg = parse_wg_config(_cfg(tmp_path))
    used = used_ipv4s(cfg)
    assert "10.8.0.1" in {str(ip) for ip in used}
    assert next_ipv4(cfg) == "10.8.0.3/32"


def test_next_ip_skips_gap_fill(tmp_path: Path):
    extra = """
[Peer]
PublicKey = CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=
AllowedIPs = 10.8.0.3/32
"""
    cfg = parse_wg_config(_cfg(tmp_path, extra))
    assert next_ipv4(cfg) == "10.8.0.4/32"
