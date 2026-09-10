from pathlib import Path

from wg_admin.wg.parse import parse_wg_config, render_wg_config
from wg_admin.wg.write import strip_runtime_config


FIXTURE = """# keep this banner

[Interface]
PrivateKey = {priv}
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -i %i -j ACCEPT
MTU = 1420

# laptop
[Peer]
PublicKey = {pub1}
AllowedIPs = 10.8.0.2/32
PersistentKeepalive = 25

# Name = phone
[Peer]
PublicKey = {pub2}
PresharedKey = {psk}
AllowedIPs = 10.8.0.3/32, 10.8.0.4/32
Endpoint = 203.0.113.9:51820
"""


def test_parse_preserves_interface_and_peer_names(tmp_path: Path):
    path = tmp_path / "wg0.conf"
    path.write_text(
        FIXTURE.format(priv="A" * 43 + "=", pub1="B" * 43 + "=", pub2="C" * 43 + "=", psk="D" * 43 + "="),
        encoding="utf-8",
    )
    cfg = parse_wg_config(path)
    assert cfg.name == "wg0"
    assert cfg.interface_value("PostUp").startswith("iptables")
    assert cfg.interface_value("MTU") == "1420"
    assert cfg.addresses() == ["10.8.0.1/24"]
    assert cfg.peers[0].name == "laptop"
    assert cfg.peers[1].name == "phone"
    assert cfg.peers[1].preshared_key.endswith("=")
    assert cfg.peers[1].allowed_ips == ["10.8.0.3/32", "10.8.0.4/32"]
    assert cfg.peers[1].endpoint == "203.0.113.9:51820"


def test_roundtrip_keeps_postup(tmp_path: Path):
    path = tmp_path / "wg0.conf"
    path.write_text(
        FIXTURE.format(priv="A" * 43 + "=", pub1="B" * 43 + "=", pub2="C" * 43 + "=", psk="D" * 43 + "="),
        encoding="utf-8",
    )
    cfg = parse_wg_config(path)
    rendered = render_wg_config(cfg)
    assert "PostUp = iptables" in rendered
    assert "PostDown = iptables" in rendered
    assert "# laptop" in rendered
    stripped = strip_runtime_config(cfg)
    assert "PostUp" not in stripped
    assert "Address" not in stripped
    assert "ListenPort = 51820" in stripped
    assert "PublicKey = " in stripped


def test_disabled_peer_roundtrip_and_strip(tmp_path: Path):
    path = tmp_path / "wg0.conf"
    path.write_text(
        FIXTURE.format(priv="A" * 43 + "=", pub1="B" * 43 + "=", pub2="C" * 43 + "=", psk="D" * 43 + "="),
        encoding="utf-8",
    )
    cfg = parse_wg_config(path)
    cfg.peers[0].disabled = True
    path.write_text(render_wg_config(cfg), encoding="utf-8")
    again = parse_wg_config(path)
    assert again.peers[0].disabled
    assert again.peers[0].name == "laptop"
    assert again.peers[0].public_key == "B" * 43 + "="
    assert again.peers[1].disabled is False
    text = path.read_text(encoding="utf-8")
    assert "wg-admin:disabled" in text
    stripped = strip_runtime_config(again)
    assert again.peers[0].public_key not in stripped
    assert again.peers[1].public_key in stripped


def test_set_interface_values_replaces_postup_keeps_private_key(tmp_path: Path):
    path = tmp_path / "wg0.conf"
    path.write_text(
        FIXTURE.format(priv="A" * 43 + "=", pub1="B" * 43 + "=", pub2="C" * 43 + "=", psk="D" * 43 + "="),
        encoding="utf-8",
    )
    cfg = parse_wg_config(path)
    cfg.set_interface_values("PostUp", ["echo a", "echo b"])
    cfg.set_interface_values("MTU", [])
    rendered = render_wg_config(cfg)
    assert "PrivateKey =" in rendered
    assert "PostUp = echo a" in rendered
    assert "PostUp = echo b" in rendered
    assert "MTU" not in rendered
    assert rendered.index("PrivateKey") < rendered.index("PostUp = echo a")
