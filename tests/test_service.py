from pathlib import Path

from wg_admin.config import Settings
from wg_admin.service import Manager, decode_peer_id, encode_peer_id
from wg_admin.wg.keys import genkey, pubkey
from wg_admin.wg.parse import parse_wg_config
from wg_admin.wg.write import strip_runtime_config


def _settings(tmp_path: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("WG_ADMIN_DEMO", "1")
    monkeypatch.setenv("WG_ADMIN_CONFIG_DIR", str(tmp_path / "wg"))
    monkeypatch.setenv("WG_ADMIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "wg").mkdir()
    priv = genkey()
    (tmp_path / "wg" / "wg0.conf").write_text(
        f"""[Interface]
PrivateKey = {priv}
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = echo up
PostDown = echo down

# imported
[Peer]
PublicKey = {pubkey(genkey())}
AllowedIPs = 10.8.0.2/32
""",
        encoding="utf-8",
    )
    return Settings()


def test_add_peer_writes_config_and_keeps_hooks(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    peer = mgr.add_peer("wg0", "laptop", "10.8.0.5/32", "25", "dev box", use_psk=True)
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.interface_value("PostUp") == "echo up"
    assert cfg.peer_by_public_key(peer.public_key) is not None
    assert mgr.state.peer("wg0", peer.public_key).private_key
    client = mgr.client_config("wg0", peer.public_key)
    assert "PrivateKey =" in client
    assert "Address = 10.8.0.5/32" in client
    assert "[Peer]" in client


def test_add_peer_from_existing_public_key(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    existing = pubkey(genkey())
    peer = mgr.add_peer("wg0", "phone", "10.8.0.8/32", "25", public_key=existing, use_psk=False)
    assert peer.public_key == existing
    assert mgr.state.peer("wg0", existing).private_key == ""
    try:
        mgr.client_config("wg0", existing)
        raise AssertionError("imported public key should not yield a client config")
    except ValueError:
        pass


def test_client_overrides_and_disable(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    peer = mgr.add_peer(
        "wg0",
        "laptop",
        "10.8.0.5/32",
        "25",
        client_dns="10.8.0.1",
        client_allowed_ips="10.8.0.0/24",
        client_endpoint="vpn.example.com:51820",
    )
    client = mgr.client_config("wg0", peer.public_key)
    assert "DNS = 10.8.0.1" in client
    assert "AllowedIPs = 10.8.0.0/24" in client
    assert "Endpoint = vpn.example.com:51820" in client
    mgr.set_peer_disabled("wg0", peer.public_key, True)
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.peer_by_public_key(peer.public_key).disabled
    assert peer.public_key not in strip_runtime_config(cfg)
    mgr.set_peer_disabled("wg0", peer.public_key, False)
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.peer_by_public_key(peer.public_key).disabled is False
    assert peer.public_key in strip_runtime_config(cfg)


def test_restore_backup(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    first = mgr.add_peer("wg0", "one", "10.8.0.5/32", "25")
    mgr.add_peer("wg0", "two", "10.8.0.6/32", "25")
    backups = mgr.backups("wg0")
    assert backups
    before_two = backups[0]
    mgr.restore_backup("wg0", before_two.stamp)
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    names = [peer.name for peer in cfg.peers]
    assert first.public_key in {peer.public_key for peer in cfg.peers}
    assert "two" not in names


def test_imported_peer_has_no_client_key(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    imported = mgr.config("wg0").peers[0]
    assert mgr.state.peer("wg0", imported.public_key).private_key == ""
    try:
        mgr.client_config("wg0", imported.public_key)
        raise AssertionError("expected missing private key")
    except ValueError:
        pass
    rotated = mgr.rotate_peer("wg0", imported.public_key)
    assert mgr.client_config("wg0", rotated.public_key)


def test_peer_id_roundtrip():
    key = "abcd+/EF0123456789+/ABCDEF+/abcdef+/ABC="
    assert decode_peer_id(encode_peer_id(key)) == key


def test_inherit_comment_names(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    mgr.inherit_names()
    imported = mgr.config("wg0").peers[0]
    assert mgr.state.peer("wg0", imported.public_key).name == "imported"


def test_save_server_interface_edits_hooks_in_place(tmp_path: Path, monkeypatch):
    mgr = Manager(_settings(tmp_path, monkeypatch))
    imported = mgr.config("wg0").peers[0].public_key
    changed = mgr.save_server_interface(
        "wg0",
        "10.8.0.1/24, fd00:8::1/64",
        "51821",
        mtu="1420",
        postup="iptables -A FORWARD -i %i -j ACCEPT\niptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
        postdown="iptables -D FORWARD -i %i -j ACCEPT",
    )
    assert changed is True
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.interface_value("PrivateKey")
    assert cfg.addresses() == ["10.8.0.1/24", "fd00:8::1/64"]
    assert cfg.listen_port() == "51821"
    assert cfg.interface_value("MTU") == "1420"
    assert cfg.interface_values("PostUp") == [
        "iptables -A FORWARD -i %i -j ACCEPT",
        "iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
    ]
    assert cfg.peer_by_public_key(imported) is not None
    unchanged = mgr.save_server_interface(
        "wg0",
        "10.8.0.1/24, fd00:8::1/64",
        "51822",
        mtu="1420",
        postup="iptables -A FORWARD -i %i -j ACCEPT\niptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
        postdown="iptables -D FORWARD -i %i -j ACCEPT",
    )
    assert unchanged is False
    mgr.bounce_interface("wg0")
