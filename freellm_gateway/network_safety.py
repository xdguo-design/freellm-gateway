from __future__ import annotations

import socket
from ipaddress import ip_address
from urllib.parse import urlparse


class UnsafeProviderTarget(ValueError):
    pass


def _address_from_host(host: str):
    try:
        return ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _is_loopback_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    address = _address_from_host(normalized)
    return bool(address and address.is_loopback)


def _is_public_address(value: str) -> bool:
    address = ip_address(value.split("%", 1)[0])
    return address.is_global


def resolve_host_addresses(host: str, port: int) -> set[str]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return set()
    addresses = set()
    for row in rows:
        sockaddr = row[4]
        if not sockaddr:
            continue
        value = str(sockaddr[0]).split("%", 1)[0]
        try:
            ip_address(value)
        except ValueError:
            continue
        addresses.add(value)
    return addresses


def validate_provider_target(value: str, *, resolve_dns: bool = True) -> None:
    parsed = urlparse(value)
    if parsed.username or parsed.password or not parsed.netloc or not parsed.hostname:
        raise UnsafeProviderTarget("provider URL must not contain credentials")

    host = parsed.hostname
    if parsed.scheme == "http":
        if _is_loopback_host(host):
            return
        raise UnsafeProviderTarget("HTTP provider URLs are allowed only for loopback development targets")

    if parsed.scheme != "https":
        raise UnsafeProviderTarget("provider URL must use HTTPS or loopback HTTP")

    literal = _address_from_host(host)
    if literal is not None and not literal.is_global:
        raise UnsafeProviderTarget("provider URL must not target a non-public IP address")

    if not resolve_dns or literal is not None:
        return

    port = parsed.port or 443
    addresses = resolve_host_addresses(host, port)
    unsafe = sorted(address for address in addresses if not _is_public_address(address))
    if unsafe:
        raise UnsafeProviderTarget(
            "provider hostname resolves to a non-public IP address: " + ", ".join(unsafe)
        )
