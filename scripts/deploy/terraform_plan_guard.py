#!/usr/bin/env python3
"""Fail routine deployment plans that destroy or replace critical hosted resources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CRITICAL_RESOURCE_TYPES = {
    "aws_cognito_user_pool",
    "aws_cognito_user_pool_client",
    "aws_db_instance",
    "aws_kms_key",
    "aws_s3_bucket",
    "aws_sqs_queue",
}


class PlanError(ValueError):
    """Raised for malformed or unsafe Terraform plan JSON."""


def inspect_plan(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    changes = data.get("resource_changes")
    if not isinstance(changes, list):
        raise PlanError("Terraform plan JSON has no resource_changes list")
    destructive: list[str] = []
    critical: list[str] = []
    for item in changes:
        if not isinstance(item, dict):
            raise PlanError("resource_changes contains a non-object entry")
        address = item.get("address")
        resource_type = item.get("type")
        change = item.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(address, str) or not isinstance(actions, list):
            raise PlanError("resource change is missing an address or actions")
        if "delete" not in actions:
            continue
        action = "replace" if "create" in actions else "destroy"
        finding = f"{action}: {address}"
        destructive.append(finding)
        if resource_type in CRITICAL_RESOURCE_TYPES:
            critical.append(finding)
    return destructive, critical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.plan.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PlanError("Terraform plan JSON must be an object")
        destructive, critical = inspect_plan(data)
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        raise SystemExit(f"Terraform plan rejected: {exc}") from exc

    lines = ["## Terraform destructive-change guard", ""]
    if destructive:
        lines.extend(["Destructive changes detected:", *[f"- {item}" for item in destructive]])
    else:
        lines.append("No destroy or replacement actions detected.")
    if critical:
        lines.extend(
            [
                "",
                "Routine deployment is blocked for critical data, identity, and encryption resources:",
                *[f"- {item}" for item in critical],
                "",
                "Use a separately reviewed break-glass infrastructure procedure.",
            ]
        )
    report = "\n".join(lines) + "\n"
    print(report, end="")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as stream:
            stream.write(report)
    if critical:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
