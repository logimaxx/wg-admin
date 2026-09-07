from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface, IPv4Network, ip_interface, ip_network

from wg_admin.wg.parse import WgConfig


def _ipv4_interface(value: str) -> IPv4Interface | None:
    try:
        parsed = ip_interface(value.split()[0])
    except ValueError:
        return None
    return parsed if isinstance(parsed, IPv4Interface) else None


def primary_ipv4_network(config: WgConfig) -> IPv4Network | None:
    for address in config.addresses():
        parsed = _ipv4_interface(address)
        if parsed is not None:
            return parsed.network
    return None


def used_ipv4s(config: WgConfig) -> set[IPv4Address]:
    used: set[IPv4Address] = set()
    for address in config.addresses():
        parsed = _ipv4_interface(address)
        if parsed is not None:
            used.add(parsed.ip)
    for peer in config.peers:
        for allowed in peer.allowed_ips:
            try:
                network = ip_network(allowed, strict=False)
            except ValueError:
                continue
            if isinstance(network, IPv4Network) and network.prefixlen == 32:
                used.add(IPv4Address(network.network_address))
    return used


def next_ipv4(config: WgConfig) -> str:
    network = primary_ipv4_network(config)
    if network is None:
        raise ValueError("Interface has no IPv4 Address to allocate from")
    used = used_ipv4s(config)
    for host in network.hosts():
        if host not in used:
            return f"{host}/32"
    raise ValueError(f"No free IPv4 addresses left in {network}")
