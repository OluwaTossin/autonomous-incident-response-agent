"""Fail-closed validation for deployment-configured outbound HTTPS destinations."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UnsafeOutboundUrl(ValueError):
    """Raised when an outbound destination is unsafe for hosted production."""


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


def validate_public_https_url(value: str, *, setting_name: str) -> str:
    """Validate a deployment-owned HTTPS URL without performing a network lookup.

    DNS and redirect handling remain the caller's responsibility. Production egress
    controls are the second line of defense against DNS rebinding.
    """
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeOutboundUrl(f"{setting_name} is not a valid URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise UnsafeOutboundUrl(f"{setting_name} must be an HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundUrl(f"{setting_name} must not contain user information")
    if port not in (None, 443):
        raise UnsafeOutboundUrl(f"{setting_name} must use the default HTTPS port")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise UnsafeOutboundUrl(f"{setting_name} must not target a local host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise UnsafeOutboundUrl(
                f"{setting_name} must not target private, local, or reserved addresses"
            )
    return candidate.rstrip("/")
