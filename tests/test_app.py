from fastapi.testclient import TestClient

from wg_admin.config import reset_settings
from wg_admin.wg.keys import genkey, pubkey
from wg_admin.wg.parse import parse_wg_config


def _boot(tmp_path, monkeypatch, main):
    monkeypatch.setenv("WG_ADMIN_DEMO", "1")
    monkeypatch.setenv("WG_ADMIN_CONFIG_DIR", str(tmp_path / "wg"))
    monkeypatch.setenv("WG_ADMIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "wg").mkdir()
    (tmp_path / "wg" / "wg0.conf").write_text(
        f"""[Interface]
PrivateKey = {genkey()}
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = echo up

# leftover
[Peer]
PublicKey = {pubkey(genkey())}
AllowedIPs = 10.8.0.2/32
""",
        encoding="utf-8",
    )
    main.bind_app(reset_settings())
    return TestClient(main.app)


def test_setup_dashboard_add_peer(tmp_path, monkeypatch):
    from wg_admin import main

    client = _boot(tmp_path, monkeypatch, main)
    setup = client.get("/setup")
    assert setup.status_code == 200
    assert "wg0.conf" in setup.text
    assert "data-theme-toggle" in setup.text

    token = setup.text.split('name="csrf" value="')[1].split('"')[0]
    posted = client.post(
        "/setup",
        data={"password": "correct-horse", "confirm": "correct-horse", "csrf": token},
        follow_redirects=False,
    )
    assert posted.status_code == 303

    home = client.get("/")
    assert home.status_code == 200
    assert "wg0" in home.text
    assert "10.8.0.1/24" in home.text

    iface = client.get("/interfaces/wg0")
    assert iface.status_code == 200
    assert "leftover" in iface.text
    assert "PostUp" in iface.text
    token = iface.text.split('name="csrf" value="')[1].split('"')[0]
    added = client.post(
        "/interfaces/wg0/peers",
        data={
            "csrf": token,
            "peer_name": "laptop",
            "allowed_ips": "10.8.0.9/32",
            "keepalive": "25",
            "use_psk": "1",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.interface_value("PostUp") == "echo up"
    created = next(peer for peer in cfg.peers if peer.allowed_ips == ["10.8.0.9/32"])
    from wg_admin.service import encode_peer_id

    download = client.get(f"/interfaces/wg0/peers/{encode_peer_id(created.public_key)}/config")
    assert download.status_code == 200
    assert "Address = 10.8.0.9/32" in download.text
    qr = client.get(f"/interfaces/wg0/peers/{encode_peer_id(created.public_key)}/qr")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert "created=" in (added.headers.get("location") or "")

    disabled = client.post(
        f"/interfaces/wg0/peers/{encode_peer_id(created.public_key)}/disable",
        data={"csrf": token},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    cfg = parse_wg_config(tmp_path / "wg" / "wg0.conf")
    assert cfg.peer_by_public_key(created.public_key).disabled

    iface = client.get("/interfaces/wg0")
    assert "disabled" in iface.text
    assert "Filter by name" in iface.text
    assert "Config backups" in iface.text
    token = iface.text.split('name="csrf" value="')[1].split('"')[0]

    existing = pubkey(genkey())
    imported = client.post(
        "/interfaces/wg0/peers",
        data={
            "csrf": token,
            "peer_name": "phone",
            "allowed_ips": "10.8.0.10/32",
            "keepalive": "25",
            "public_key": existing,
        },
        follow_redirects=False,
    )
    assert imported.status_code == 303
    assert "created=" not in (imported.headers.get("location") or "")

    account = client.get("/account")
    assert account.status_code == 200
    token = account.text.split('name="csrf" value="')[1].split('"')[0]
    changed = client.post(
        "/account",
        data={
            "csrf": token,
            "current": "correct-horse",
            "password": "new-password",
            "confirm": "new-password",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    client.post("/logout", data={"csrf": token}, follow_redirects=False)
    login = client.get("/login")
    token = login.text.split('name="csrf" value="')[1].split('"')[0]
    denied = client.post(
        "/login",
        data={"password": "correct-horse", "csrf": token},
        follow_redirects=False,
    )
    assert denied.status_code == 401
    allowed = client.post(
        "/login",
        data={"password": "new-password", "csrf": token},
        follow_redirects=False,
    )
    assert allowed.status_code == 303
