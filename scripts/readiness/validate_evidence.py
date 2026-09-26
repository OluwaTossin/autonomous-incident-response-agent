#!/usr/bin/env python3
"""Evaluate readiness evidence without deploying or mutating resources."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from scripts.readiness.evidence import ReleaseIdentity, evaluate, load_evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--expected-release", type=Path, required=True)
    args = parser.parse_args()
    expected = ReleaseIdentity.from_dict(load_evidence(args.expected_release))
    result = evaluate(load_evidence(args.evidence), expected_release=expected)
    print(json.dumps(asdict(result), indent=2))
    if result.decision != "GO":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
