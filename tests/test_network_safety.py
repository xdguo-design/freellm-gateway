import socket

import pytest

from freellm_gateway.network_safety import (
    UnsafeProviderTarget,
    validate_provider_target,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v1",
        "https://127.0.0.2/v1",
        "https://10.0.0.1/v1",
        "https://172.16.0.1/v1",
        "https://192.168.1.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/v1",
        "https://224.0.0.1/v1",
        "https://[::1]/v1",
        "https://[fc00::1]/v1",
        "https://[fe80::1]/v1",
    ],
)
def test_provider_target_rejects_non_public_https_literals(url):
    with pytest.raises(UnsafeProviderTarget):
        validate_provider_target(url, resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
    ],
)
def test_provider_target_allows_loopback_http_for_local_development(url):
    validate_provider_target(url, resolve_dns=False)


def test_provider_target_rejects_non_loopback_http():
    with pytest.raises(UnsafeProviderTarget):
        validate_provider_target("http://10.0.0.5:8080/v1", resolve_dns=False)


def test_provider_target_rejects_hostname_that_resolves_private(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.10.0.8", 443)),
        ],
    )

    with pytest.raises(UnsafeProviderTarget, match="non-public"):
        validate_provider_target("https://provider.example/v1")


def test_provider_target_rejects_mixed_public_and_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.7", 443)),
        ],
    )

    with pytest.raises(UnsafeProviderTarget, match="non-public"):
        validate_provider_target("https://provider.example/v1")


def test_provider_target_allows_public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )

    validate_provider_target("https://provider.example/v1")


def test_provider_target_does_not_turn_dns_outage_into_configuration_corruption(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("offline")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    validate_provider_target("https://provider.example/v1")
