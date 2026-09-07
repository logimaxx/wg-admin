from wg_admin.wg.runtime import parse_wg_dump

PUB = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="
PSK = "(none)"
IFACE_PUB = "jUd41n3Cv38c6ns8sM8hcmvqC0ZBQJqhcUk/ekeqVG8="


def test_parse_all_dump_peer_rows_include_interface_name():
    dump = "\n".join(
        [
            f"wg0\toff\t{IFACE_PUB}\t51820\toff",
            f"wg0\t{PUB}\t{PSK}\t(none)\t10.66.0.3/32\t0\t0\t0\toff",
        ]
    )
    runtime = parse_wg_dump(dump, iface_is_up=lambda _name: True)
    iface = runtime.for_interface("wg0")
    assert iface.up
    assert iface.listen_port == "51820"
    peer = iface.peers[PUB]
    assert peer.allowed_ips == "10.66.0.3/32"
    assert peer.latest_handshake == 0
    assert peer.persistent_keepalive == 0
    assert peer.endpoint == ""


def test_parse_all_dump_live_peer():
    dump = "\n".join(
        [
            f"wg0\toff\t{IFACE_PUB}\t51820\toff",
            f"wg0\t{PUB}\t{PSK}\t203.0.113.9:51820\t10.66.0.3/32\t1710000000\t1024\t2048\t25",
        ]
    )
    runtime = parse_wg_dump(dump, iface_is_up=lambda _name: False)
    peer = runtime.for_interface("wg0").peers[PUB]
    assert peer.endpoint == "203.0.113.9:51820"
    assert peer.latest_handshake == 1710000000
    assert peer.transfer_rx == 1024
    assert peer.transfer_tx == 2048
    assert peer.persistent_keepalive == 25


def test_parse_peer_row_without_interface_prefix():
    dump = "\n".join(
        [
            f"wg0\toff\t{IFACE_PUB}\t51820\toff",
            f"{PUB}\t{PSK}\t(none)\t10.8.0.2/32\t0\t0\t0\toff",
        ]
    )
    runtime = parse_wg_dump(dump, iface_is_up=lambda _name: True)
    assert PUB in runtime.for_interface("wg0").peers
    assert runtime.for_interface("wg0").peers[PUB].allowed_ips == "10.8.0.2/32"
