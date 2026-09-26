"""Safe machine-readable migration report serialization."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.migration.service import MigrationReport


def migration_report_dict(report: MigrationReport) -> dict:
    data = asdict(report)
    data["started_at"] = report.started_at.isoformat()
    data["completed_at"] = report.completed_at.isoformat()
    data["document_count_verified"] = sum(
        record.status == "verified" for record in report.records
    )
    data["document_bytes_verified"] = (
        report.document_bytes_impact if report.mode == "verify" else None
    )
    return data


def write_migration_report(path: Path, report: MigrationReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(migration_report_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def format_migration_report(report: MigrationReport) -> str:
    """Render the same safe report as a compact operator-readable summary."""
    lines = [
        f"Migration {report.migration_id}",
        f"Mode: {report.mode}",
        f"Manifest: {report.manifest_hash}",
        f"Destination: {report.organization_id}/{report.workspace_id}",
        (
            "Records: "
            f"imported={report.imported} skipped={report.skipped} "
            f"rejected={report.rejected} failed={report.failed}"
        ),
        (
            "Document impact: "
            f"count={report.document_count_impact} "
            f"bytes={report.document_bytes_impact}"
        ),
        f"Historical-only records: {report.historical_only_records}",
        f"Knowledge rebuild required: {str(report.knowledge_rebuild_required).lower()}",
        f"Result: {'clean' if report.clean else 'not clean'}",
    ]
    if report.unmapped_items:
        lines.append("Unmapped/omitted: " + ", ".join(report.unmapped_items))
    return "\n".join(lines)
