"""Versioned, identifier-only SQS envelope for durable job dispatch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.domain.identifiers import CorrelationId, JobId, OrganizationId, WorkspaceId


class MessageEnvelopeError(ValueError):
    """A transport message cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class JobDispatchEnvelope:
    job_id: JobId
    dispatch_id: UUID
    dispatch_generation: int
    routing_organization_id: OrganizationId
    routing_workspace_id: WorkspaceId
    correlation_id: CorrelationId | None = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2}:
            raise MessageEnvelopeError("Unsupported job message schema version")
        if self.schema_version == 2 and self.correlation_id is None:
            raise MessageEnvelopeError("Version 2 job messages require correlation")
        if self.schema_version == 1 and self.correlation_id is not None:
            raise MessageEnvelopeError("Version 1 job messages do not carry correlation")
        if self.dispatch_generation < 1:
            raise MessageEnvelopeError("Dispatch generation must be positive")

    def to_json(self) -> str:
        value = {
                "schema_version": self.schema_version,
                "job_id": str(self.job_id),
                "dispatch_id": str(self.dispatch_id),
                "dispatch_generation": self.dispatch_generation,
                # Routing hints are re-authorized and matched to PostgreSQL rows.
                "routing_organization_id": str(self.routing_organization_id),
                "routing_workspace_id": str(self.routing_workspace_id),
            }
        if self.correlation_id is not None:
            value["correlation_id"] = str(self.correlation_id)
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> JobDispatchEnvelope:
        if not isinstance(raw, str) or not raw or len(raw) > 16_384:
            raise MessageEnvelopeError("Invalid job message body")
        try:
            value: Any = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise MessageEnvelopeError("Invalid job message JSON") from exc
        if not isinstance(value, dict):
            raise MessageEnvelopeError("Job message must be an object")
        common = {
            "schema_version",
            "job_id",
            "dispatch_id",
            "dispatch_generation",
            "routing_organization_id",
            "routing_workspace_id",
        }
        try:
            schema_version = _strict_int(value.get("schema_version"))
        except (TypeError, ValueError) as exc:
            raise MessageEnvelopeError("Job message version is invalid") from exc
        expected = common | ({"correlation_id"} if schema_version == 2 else set())
        if set(value) != expected:
            raise MessageEnvelopeError("Job message fields are invalid")
        try:
            return cls(
                schema_version=schema_version,
                job_id=JobId(str(value["job_id"])),
                dispatch_id=UUID(str(value["dispatch_id"])),
                dispatch_generation=_strict_int(value["dispatch_generation"]),
                routing_organization_id=OrganizationId(
                    str(value["routing_organization_id"])
                ),
                routing_workspace_id=WorkspaceId(str(value["routing_workspace_id"])),
                correlation_id=(
                    CorrelationId(str(value["correlation_id"]))
                    if schema_version == 2
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise MessageEnvelopeError("Job message identifiers are invalid") from exc


def _strict_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Expected integer")
    return value
