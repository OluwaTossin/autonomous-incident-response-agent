#!/usr/bin/env python3
"""Small allowlisted HTTP load probe for localhost or explicitly approved staging."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from scripts.readiness.capacity import percentile

SYNTHETIC_MARKER = "AIRA_SYNTHETIC_DO_NOT_ESCALATE"


def validate_target(base_url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target must be an HTTP(S) origin")
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not local and parsed.hostname not in allowed_hosts:
        raise ValueError("target host is not explicitly allowlisted")
    if any(label in parsed.hostname.casefold() for label in ("prod", "production")):
        raise ValueError("production-like targets are always rejected")
    return base_url.rstrip("/")


def run_probe(url: str, *, requests: int, concurrency: int) -> dict[str, object]:
    def request_once() -> tuple[float, bool]:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
                ok = 200 <= response.status < 400
        except (OSError, urllib.error.URLError):
            ok = False
        return (time.monotonic() - started) * 1000, ok

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        samples = list(executor.map(lambda _index: request_once(), range(requests)))
    latencies = [latency for latency, _ok in samples]
    successes = sum(ok for _latency, ok in samples)
    return {
        "marker": SYNTHETIC_MARKER,
        "requests": requests,
        "successes": successes,
        "error_rate": (requests - successes) / requests,
        "latency_ms": {"p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95), "p99": percentile(latencies, 0.99)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--path", default="/healthz")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.requests <= 10000 or not 1 <= args.concurrency <= 100:
        raise SystemExit("requests/concurrency are outside safety bounds")
    base = validate_target(args.base_url, set(args.allow_host))
    print(json.dumps(run_probe(base + args.path, requests=args.requests, concurrency=args.concurrency)))


if __name__ == "__main__":
    main()
