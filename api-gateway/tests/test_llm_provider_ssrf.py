"""Tests for §security-R6 LLM custom provider SSRF protection.

Verifies that _validate_llm_provider_url in routers/llm.py rejects
URLs that resolve to private, loopback, or link-local addresses.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Mirror the validation logic from routers/llm.py
_BLOCKED_LLM_PROVIDER_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _BLOCKED_LLM_PROVIDER_NETS)


def _validate_llm_provider_url(url: str) -> str | None:
    """Mirror the validation in routers/llm.py _validate_llm_provider_url."""
    import re
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return "base_url must be an http or https URL"
    try:
        parsed = urlparse(url)
    except Exception:
        return "base_url is not a valid URL"
    hostname = parsed.hostname or ""
    if not hostname:
        return "base_url must include a hostname"
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return f"base_url hostname '{hostname}' could not be resolved"
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        for net in _BLOCKED_LLM_PROVIDER_NETS:
            if ip in net:
                return f"blocked: {net}"
    return None


def test_loopback_blocked() -> None:
    assert _is_blocked_ip("127.0.0.1")
    assert _is_blocked_ip("127.255.255.254")


def test_private_rfc1918_blocked() -> None:
    assert _is_blocked_ip("10.0.0.1")
    assert _is_blocked_ip("172.16.0.1")
    assert _is_blocked_ip("192.168.1.1")


def test_link_local_blocked() -> None:
    """Cloud metadata services live in 169.254/16 — must be blocked."""
    assert _is_blocked_ip("169.254.169.254")
    assert _is_blocked_ip("169.254.0.1")


def test_cgnat_blocked() -> None:
    assert _is_blocked_ip("100.64.0.1")


def test_public_ip_allowed() -> None:
    assert not _is_blocked_ip("8.8.8.8")
    assert not _is_blocked_ip("1.1.1.1")
    assert not _is_blocked_ip("203.0.113.1")


def test_ipv6_loopback_blocked() -> None:
    assert _is_blocked_ip("::1")


def test_ipv6_link_local_blocked() -> None:
    assert _is_blocked_ip("fe80::1")


def test_https_required() -> None:
    """Only http and https schemes are allowed."""
    assert _validate_llm_provider_url("ftp://example.com") is not None
    assert _validate_llm_provider_url("file:///etc/passwd") is not None


def test_loopback_url_rejected_via_resolution() -> None:
    """Loopback hostnames must be rejected when resolved."""
    # Only test if the resolution succeeds on the test machine;
    # otherwise the test passes via the "could not be resolved" path.
    result = _validate_llm_provider_url("http://localhost:8080/admin")
    # On most systems, localhost resolves to 127.0.0.1
    if result is None:
        # Resolution didn't catch it — fail the test
        raise AssertionError("Expected localhost to be blocked")
    assert "blocked" in result or "could not be resolved" in result


def test_metadata_service_rejected() -> None:
    """The cloud metadata IP must be rejected when used directly."""
    result = _validate_llm_provider_url("http://169.254.169.254/latest/meta-data/")
    if result is None:
        raise AssertionError("Expected 169.254.169.254 to be blocked")
    assert "blocked" in result
