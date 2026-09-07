from pathlib import Path

from wg_admin.config import Settings
from wg_admin.service import Manager, decode_peer_id, encode_peer_id
from wg_admin.wg.keys import genkey, pubkey
from wg_admin.wg.parse import parse_wg_config


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
