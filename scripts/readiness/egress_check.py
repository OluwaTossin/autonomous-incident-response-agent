#!/usr/bin/env python3
"""Allowlisted DNS/TLS metadata check that sends no application or customer data."""

from __future__ import annotations

import argparse
import socket
import ssl
from dataclasses import asdict, dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class TlsEvidence:
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...]
    certificate_subject: str
    certificate_expires: str


def validate_endpoint(url: str, allowed_hosts: set[str]) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("egress endpoint must be an HTTPS hostname without userinfo")
    if parsed.hostname not in allowed_hosts:
        raise ValueError("egress hostname is not explicitly allowlisted")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("egress check accepts an origin only")
    return parsed.hostname, parsed.port or 443


def check_tls(hostname: str, port: int, *, timeout_seconds: float = 5) -> TlsEvidence:
    addresses = tuple(sorted({item[4][0] for item in socket.getaddrinfo(hostname, port)}))
    context = ssl.create_default_context()
    with socket.create_connection((hostname, port), timeout=timeout_seconds) as raw:
        with context.wrap_socket(raw, server_hostname=hostname) as connection:
            certificate = connection.getpeercert()
    subject = ",".join("=".join(attribute) for group in certificate.get("subject", ()) for attribute in group)
    return TlsEvidence(hostname, port, addresses, subject, str(certificate.get("notAfter", "")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--allow-host", action="append", required=True)
    args = parser.parse_args()
    host, port = validate_endpoint(args.url, set(args.allow_host))
    import json

    print(json.dumps(asdict(check_tls(host, port)), indent=2))


if __name__ == "__main__":
    main()
