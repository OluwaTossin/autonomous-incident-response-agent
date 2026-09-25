"""Static connector mapping and local preparation with no execution capability."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.actions import (
    AcknowledgeIncidentParameters,
    ActionProposal,
    ActionProposalType,
    ActionTargetProvenance,
    ActionTargetType,
)
from app.domain.execution import ConnectorKind, OperationKind


class ConnectorValidationCode(StrEnum):
    UNSUPPORTED_ACTION = "unsupported_action"
    TARGET_NOT_AUTHORITATIVE = "target_not_authoritative"
    PARAMETERS_INVALID = "parameters_invalid"


class ConnectorValidationError(ValueError):
    def __init__(self, code: ConnectorValidationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreparedOperation:
    connector_kind: ConnectorKind
    operation_kind: OperationKind
    provider: str
    request_schema_version: int
    target_identifier: str
    validation_status: str = "passed"


class InternalActionConnector:
    """Prepares one allowlisted internal operation and cannot execute it."""

    kind = ConnectorKind.INTERNAL

    def prepare(self, proposal: ActionProposal) -> PreparedOperation:
        if proposal.proposal_type is not ActionProposalType.ACKNOWLEDGE_INCIDENT:
            raise ConnectorValidationError(
                ConnectorValidationCode.UNSUPPORTED_ACTION,
                "Action type has no controlled connector mapping",
            )
        if not isinstance(proposal.parameters, AcknowledgeIncidentParameters):
            raise ConnectorValidationError(
                ConnectorValidationCode.PARAMETERS_INVALID,
                "Action parameters do not match the connector operation",
            )
        if (
            proposal.target.type is not ActionTargetType.INCIDENT
            or proposal.target.provenance is not ActionTargetProvenance.INCIDENT
            or proposal.target.provider != "aira"
            or proposal.target.identifier != str(proposal.incident.id)
        ):
            raise ConnectorValidationError(
                ConnectorValidationCode.TARGET_NOT_AUTHORITATIVE,
                "Incident target is not authoritative",
            )
        return PreparedOperation(
            ConnectorKind.INTERNAL,
            OperationKind.ACKNOWLEDGE_INCIDENT,
            "aira",
            1,
            proposal.target.identifier,
        )


class ActionConnectorRegistry:
    """Closed deterministic registry; database or model output cannot add connectors."""

    def __init__(self) -> None:
        self._internal = InternalActionConnector()

    def prepare(self, proposal: ActionProposal) -> PreparedOperation:
        if proposal.target.type is ActionTargetType.AWS_RESOURCE:
            raise ConnectorValidationError(
                ConnectorValidationCode.TARGET_NOT_AUTHORITATIVE,
                "No AWS operation has sufficient authoritative target identity",
            )
        return self._internal.prepare(proposal)
