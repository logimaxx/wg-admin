#!/usr/bin/env python3
"""Render README screenshots from a throwaway demo instance."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8765
PASSWORD = "screenshot-pass"
OUT = ROOT / "docs" / "screenshots"


def _write_configs(config_dir: Path) -> None:
    from wg_admin.wg.keys import genkey, pubkey

    keys = {name: genkey() for name in ("wg0", "alice", "bob", "office", "wg1", "siteb")}
    pub = {name: pubkey(priv) for name, priv in keys.items()}

    (config_dir / "wg0.conf").write_text(
        f"""# Production road-warrior interface
# Inherited by wg-admin on first start

[Interface]
PrivateKey = {keys["wg0"]}
Address = 10.8.0.1/24
ListenPort = 51820
SaveConfig = false
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Alice laptop
[Peer]
PublicKey = {pub["alice"]}
AllowedIPs = 10.8.0.2/32
PersistentKeepalive = 25

# Bob phone
[Peer]
PublicKey = {pub["bob"]}
AllowedIPs = 10.8.0.3/32

# Office router
[Peer]
PublicKey = {pub["office"]}
AllowedIPs = 10.8.0.4/32, 10.20.0.0/24
Endpoint = office.example.net:51820
""",
        encoding="utf-8",
    )
    (config_dir / "wg1.conf").write_text(
        f"""[Interface]
PrivateKey = {keys["wg1"]}
Address = 10.10.10.1/24
ListenPort = 51821
MTU = 1420

# Site B
[Peer]
PublicKey = {pub["siteb"]}
AllowedIPs = 10.10.10.2/32, 192.168.50.0/24
PersistentKeepalive = 15
""",
        encoding="utf-8",
    )


def _peer_map(config_dir: Path) -> dict[tuple[str, str], str]:
    from wg_admin.wg.parse import load_configs

    named: dict[tuple[str, str], str] = {}
    for config in load_configs(config_dir):
        named[(config.name, "iface")] = (
            next((value for key, value in config.interface if key.lower() == "privatekey"), "")
        )
        for peer in config.peers:
            named[(config.name, peer.name)] = peer.public_key
    return named


def _install_demo_runtime(config_dir: Path) -> None:
    from wg_admin.wg.keys import pubkey
    from wg_admin.wg.runtime import parse_wg_dump
    import wg_admin.service as service

    named = _peer_map(config_dir)
    now = int(time.time())
    wg0_pub = pubkey(named[("wg0", "iface")])
    wg1_pub = pubkey(named[("wg1", "iface")])
    dump = "\n".join(
        [
            f"wg0\t(hidden)\t{wg0_pub}\t51820\toff",
            f"wg0\t{named[('wg0', 'Alice laptop')]}\t(none)\t203.0.113.10:41641\t10.8.0.2/32\t{now - 18}\t1843200\t932120\t25",
            f"wg0\t{named[('wg0', 'Bob phone')]}\t(none)\t198.51.100.44:51820\t10.8.0.3/32\t{now - 420}\t51200\t40960\toff",
            f"wg0\t{named[('wg0', 'Office router')]}\t(none)\toffice.example.net:51820\t10.8.0.4/32,10.20.0.0/24\t{now - 40}\t89128960\t120586240\t25",
            f"wg1\t(hidden)\t{wg1_pub}\t51821\toff",
            f"wg1\t{named[('wg1', 'Site B')]}\t(none)\t203.0.113.80:51821\t10.10.10.2/32,192.168.50.0/24\t{now - 12}\t2457600\t1966080\t15",
        ]
    )

    def fake_load_runtime(demo: bool = False):
        return parse_wg_dump(dump, iface_is_up=lambda _name: True)

    service.load_runtime = fake_load_runtime


def _serve() -> None:
    config_dir = Path(os.environ["WG_ADMIN_CONFIG_DIR"])
    _install_demo_runtime(config_dir)
    from wg_admin.config import reset_settings
    from wg_admin.main import app, bind_app
    import uvicorn

    bind_app(reset_settings())
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["WG_ADMIN_PORT"]), log_level="warning")


def _wait_ready() -> None:
    import urllib.error
    import urllib.request

    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/setup", timeout=1)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(0.1)
    raise RuntimeError("demo server did not start")


def _hide_demo_chrome(page, banners: bool = False) -> None:
    page.evaluate(
        """(dropBanners) => {
          document.querySelectorAll('.pill-demo').forEach((el) => el.remove());
          if (dropBanners) {
            document.querySelectorAll('.banner').forEach((el) => el.remove());
          }
          const rewrite = (el) => {
            el.innerHTML = el.innerHTML.replace(/\\/tmp\\/wg-admin-shots-[^/\\s<]+\\/wireguard/g, '/etc/wireguard');
          };
          document.querySelectorAll('.lede, code').forEach(rewrite);
        }""",
        banners,
    )


def _shot(page, name: str, full_page: bool = True, banners: bool = False) -> None:
    _hide_demo_chrome(page, banners=banners)
    page.screenshot(path=str(OUT / name), full_page=full_page, type="png")
    print(f"wrote {OUT / name}")


def _capture() -> None:
    from playwright.sync_api import sync_playwright

    chromium = "/snap/bin/chromium"
    launch_kwargs = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    if Path(chromium).exists():
        launch_kwargs["executable_path"] = chromium

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
        base = f"http://127.0.0.1:{PORT}"

        page.goto(f"{base}/setup", wait_until="networkidle")
        _shot(page, "setup.png")

        page.fill('input[name="password"]', PASSWORD)
        page.fill('input[name="confirm"]', PASSWORD)
        page.locator("form").evaluate("form => form.submit()")
        page.wait_for_function("() => location.pathname === '/'")
        page.wait_for_load_state("networkidle")
        _shot(page, "dashboard.png", banners=True)

        page.locator("a.iface-card", has_text="wg0").click()
        page.wait_for_function("() => location.pathname === '/interfaces/wg0'")
        page.wait_for_load_state("networkidle")
        page.fill('input[name="endpoint"]', "vpn.example.com:51820")
        page.fill('input[name="client_dns"]', "10.8.0.1")
        page.fill('input[name="client_allowed_ips"]', "0.0.0.0/0, ::/0")
        page.evaluate("window.scrollTo(0, 0)")
        page.set_viewport_size({"width": 1280, "height": 1280})
        _shot(page, "interface.png", full_page=False, banners=True)
        page.set_viewport_size({"width": 1280, "height": 800})

        page.set_viewport_size({"width": 1280, "height": 920})
        page.click('button[data-open="add-peer"]')
        page.wait_for_selector("#add-peer:not([hidden])")
        _shot(page, "add-peer.png", full_page=False)
        page.set_viewport_size({"width": 1280, "height": 800})

        page.locator('#add-peer input[name="peer_name"]').fill("Sergiu laptop")
        page.locator("#add-peer form").evaluate("form => form.submit()")
        page.wait_for_function("() => location.pathname === '/interfaces/wg0'")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#qr-modal:not([hidden])")
        page.wait_for_function(
            "() => { const img = document.getElementById('qr-image'); return img && img.complete && img.naturalWidth > 0; }"
        )
        _shot(page, "qr.png", full_page=False, banners=True)
        browser.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wg-admin-shots-") as tmp:
        tmp_path = Path(tmp)
        config_dir = tmp_path / "wireguard"
        state_dir = tmp_path / "state"
        config_dir.mkdir()
        state_dir.mkdir()
        _write_configs(config_dir)

        env = os.environ.copy()
        env.update(
            {
                "WG_ADMIN_SHOT_SERVER": "1",
                "WG_ADMIN_DEMO": "1",
                "WG_ADMIN_CONFIG_DIR": str(config_dir),
                "WG_ADMIN_STATE_DIR": str(state_dir),
                "WG_ADMIN_HOST": "127.0.0.1",
                "WG_ADMIN_PORT": str(PORT),
                "PYTHONPATH": str(ROOT),
            }
        )
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=str(ROOT),
            env=env,
        )
        try:
            _wait_ready()
            _capture()
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    if os.environ.get("WG_ADMIN_SHOT_SERVER") == "1":
        _serve()
        raise SystemExit(0)
    raise SystemExit(main())
