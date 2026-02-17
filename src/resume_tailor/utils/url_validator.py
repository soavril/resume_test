"""URL validation utility to prevent SSRF attacks.

Blocks requests to internal/private network addresses before any URL access.

NOTE: This validation is subject to DNS rebinding (TOCTOU) attacks. The hostname
is resolved here, but Playwright re-resolves it when opening the browser. An
attacker controlling DNS could return a public IP during validation and a private
IP on the second resolution. For full protection, use a network-level egress
filter or proxy in production.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFError(ValueError):
    """Raised when a URL resolves to a blocked (private/internal) address."""


_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}

# Cloud metadata and special IPs that may bypass is_private checks
_BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure metadata
    ipaddress.ip_address("0.0.0.0"),
}


def validate_url(url: str) -> str:
    """Validate that a URL does not point to an internal/private network.

    Returns the validated URL string on success.
    Raises SSRFError if the URL targets a private/internal address.
    Raises ValueError if the URL is malformed.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"No hostname in URL: {url!r}")

    # Block known internal hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFError(f"Blocked internal hostname: {hostname!r}")

    # Try to parse as IP literal first
    try:
        addr = ipaddress.ip_address(hostname)
        if addr in _BLOCKED_IPS or addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise SSRFError(f"Blocked private/internal IP: {addr}")
        return url
    except ValueError:
        pass  # Not an IP literal, resolve the hostname

    # Resolve hostname and check all resulting IPs
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname {hostname!r}: {exc}") from exc

    for family, _type, _proto, _canonname, sockaddr in results:
        ip_str = sockaddr[0]
        addr = ipaddress.ip_address(ip_str)
        if addr in _BLOCKED_IPS or addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise SSRFError(
                f"Hostname {hostname!r} resolves to blocked address: {addr}"
            )

    return url
