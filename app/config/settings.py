"""Pydantic-backed settings: ``.env``, environment, optional ``CONFIG_YAML``.

Precedence for keys present in both files: **environment (and ``.env`` via load_dotenv)
overrides YAML**. Only keys listed on the model are read from YAML.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _flatten_yaml(raw: dict[str, Any]) -> dict[str, str]:
    """YAML root must be a mapping; keys normalized to UPPER_SNAKE strings."""
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        key = k.strip().upper()
        if v is None:
            continue
        if isinstance(v, bool):
            out[key] = "1" if v else "0"
        else:
            out[key] = str(v)
    return out


def _yaml_path() -> Path | None:
    raw = os.environ.get("CONFIG_YAML", "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = project_root() / p
    return p if p.is_file() else None


def _operator_overrides_path(effective: dict[str, str]) -> Path:
    """Workspace file merged after ``CONFIG_YAML`` and before process environment (see ``_merged_env_dict``)."""
    wid = (effective.get("WORKSPACE_ID") or "default").strip() or "default"
    root_name = (effective.get("WORKSPACES_ROOT") or "workspaces").strip() or "workspaces"
    return project_root() / root_name / wid / "config" / "operator_overrides.yaml"


class Settings(BaseModel):
    """Application settings: optional ``CONFIG_YAML``, then ``.env`` / process environment."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_base: str = Field(default="", validation_alias="OPENAI_API_BASE")
    embedding_model: str = Field(default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL")
    # Empty → ``workspaces/<WORKSPACE_ID>/index`` (see ``app/workspace/paths.py``).
    rag_index_dir: str = Field(default="", validation_alias="RAG_INDEX_DIR")
    workspace_id: str = Field(default="default", validation_alias="WORKSPACE_ID")
    workspaces_root: str = Field(default="workspaces", validation_alias="WORKSPACES_ROOT")
    # Override corpus root (absolute or repo-relative). Empty → workspace ``data/`` if it has
    # corpus files, else legacy ``data/`` at repo root.
    rag_corpus_root: str = Field(default="", validation_alias="RAG_CORPUS_ROOT")
    # When true, corpus root is always workspace ``data/`` (``product-build-index`` sets this).
    rag_workspace_corpus_only: bool = Field(default=False, validation_alias="RAG_WORKSPACE_ONLY")
    # ``demo`` — empty workspace uses bundled ``sample_data/default_demo/``. ``user`` — only workspace ``data/``.
    aira_data_mode: str = Field(default="demo", validation_alias="AIRA_DATA_MODE")

    llm_model: str = Field(default="gpt-4o-mini", validation_alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.2, validation_alias="LLM_TEMPERATURE")
    rag_top_k: int = Field(default=8, validation_alias="RAG_TOP_K")

    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    api_key: str = Field(default="", validation_alias="API_KEY")
    admin_api_key: str = Field(default="", validation_alias="ADMIN_API_KEY")

    api_rate_limit_disabled: bool = Field(default=False, validation_alias="API_RATE_LIMIT_DISABLED")
    api_rate_limit_triage: str = Field(default="", validation_alias="API_RATE_LIMIT_TRIAGE")
    api_rate_limit_ingest: str = Field(default="", validation_alias="API_RATE_LIMIT_INGEST")
    api_rate_limit_admin_read: str = Field(default="", validation_alias="API_RATE_LIMIT_ADMIN_READ")
    api_rate_limit_admin_upload: str = Field(default="", validation_alias="API_RATE_LIMIT_ADMIN_UPLOAD")
    api_rate_limit_admin_reindex: str = Field(default="", validation_alias="API_RATE_LIMIT_ADMIN_REINDEX")
    admin_upload_max_bytes: int = Field(default=5_242_880, validation_alias="ADMIN_UPLOAD_MAX_BYTES")

    cors_origins: str = Field(default="", validation_alias="CORS_ORIGINS")
    enable_gradio_ui: str = Field(default="1", validation_alias="ENABLE_GRADIO_UI")

    aira_env: str = Field(default="local", validation_alias="AIRA_ENV")
    aira_build_sha: str = Field(default="unknown", validation_alias="AIRA_BUILD_SHA")
    aira_metric_namespace: str = Field(
        default="AIRA/Hosted", validation_alias="AIRA_METRIC_NAMESPACE"
    )
    aira_otel_exporter_endpoint: str = Field(
        default="", validation_alias="AIRA_OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    aira_trace_sample_ratio: float = Field(
        default=0.05,
        ge=0,
        le=1,
        validation_alias="AIRA_TRACE_SAMPLE_RATIO",
    )

    # Hosted-only database URLs. Empty keeps every Version 2 command PostgreSQL-independent.
    aira_database_url: str = Field(default="", validation_alias="AIRA_DATABASE_URL")
    aira_database_migration_url: str = Field(
        default="",
        validation_alias="AIRA_DATABASE_MIGRATION_URL",
    )

    # Hosted queue/worker deployment settings. Credentials use the AWS provider chain.
    aira_sqs_queue_url: str = Field(default="", validation_alias="AIRA_SQS_QUEUE_URL")
    aira_aws_region: str = Field(default="us-east-1", validation_alias="AIRA_AWS_REGION")
    aira_aws_trusted_principal_arn: str = Field(
        default="", validation_alias="AIRA_AWS_TRUSTED_PRINCIPAL_ARN"
    )
    aira_aws_source_role_arn: str = Field(
        default="", validation_alias="AIRA_AWS_SOURCE_ROLE_ARN"
    )
    aira_public_origin: str = Field(
        default="", validation_alias="AIRA_PUBLIC_ORIGIN"
    )
    aira_document_bucket: str = Field(
        default="", validation_alias="AIRA_DOCUMENT_BUCKET"
    )
    aira_knowledge_bucket: str = Field(
        default="", validation_alias="AIRA_KNOWLEDGE_BUCKET"
    )
    aira_kms_key_arn: str = Field(
        default="", validation_alias="AIRA_KMS_KEY_ARN"
    )
    aira_alert_queue_url: str = Field(
        default="", validation_alias="AIRA_ALERT_QUEUE_URL"
    )
    aira_worker_scope_grants: str = Field(
        default="", validation_alias="AIRA_WORKER_SCOPE_GRANTS"
    )
    aira_workload_subject: str = Field(
        default="", validation_alias="AIRA_WORKLOAD_SUBJECT"
    )
    aira_sts_endpoint_url: str = Field(
        default="", validation_alias="AIRA_STS_ENDPOINT_URL"
    )
    aira_aws_verification_connect_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        validation_alias="AIRA_AWS_VERIFICATION_CONNECT_TIMEOUT_SECONDS",
    )
    aira_aws_verification_read_timeout_seconds: float = Field(
        default=8.0,
        gt=0,
        validation_alias="AIRA_AWS_VERIFICATION_READ_TIMEOUT_SECONDS",
    )
    aira_aws_verification_max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias="AIRA_AWS_VERIFICATION_MAX_ATTEMPTS",
    )
    # Hosted incident-time CloudWatch collection. Values are deployment-owned bounds.
    aira_context_metric_lookback_seconds: int = Field(
        default=900, ge=60, le=86400, validation_alias="AIRA_CONTEXT_METRIC_LOOKBACK_SECONDS"
    )
    aira_context_log_lookback_seconds: int = Field(
        default=900, ge=60, le=86400, validation_alias="AIRA_CONTEXT_LOG_LOOKBACK_SECONDS"
    )
    aira_context_forward_seconds: int = Field(
        default=120, ge=0, le=900, validation_alias="AIRA_CONTEXT_FORWARD_SECONDS"
    )
    aira_context_max_metric_points: int = Field(
        default=120, ge=1, le=1000, validation_alias="AIRA_CONTEXT_MAX_METRIC_POINTS"
    )
    aira_context_max_log_events: int = Field(
        default=100, ge=1, le=1000, validation_alias="AIRA_CONTEXT_MAX_LOG_EVENTS"
    )
    aira_context_max_log_bytes: int = Field(
        default=65536, ge=1024, le=1048576, validation_alias="AIRA_CONTEXT_MAX_LOG_BYTES"
    )
    aira_context_max_provider_calls: int = Field(
        default=8, ge=2, le=50, validation_alias="AIRA_CONTEXT_MAX_PROVIDER_CALLS"
    )
    aira_context_max_chars: int = Field(
        default=80000, ge=4096, le=500000, validation_alias="AIRA_CONTEXT_MAX_CHARS"
    )
    aira_sqs_endpoint_url: str = Field(
        default="", validation_alias="AIRA_SQS_ENDPOINT_URL"
    )
    aira_sqs_long_poll_seconds: int = Field(
        default=20, ge=0, le=20, validation_alias="AIRA_SQS_LONG_POLL_SECONDS"
    )
    aira_sqs_receive_batch_size: int = Field(
        default=10, ge=1, le=10, validation_alias="AIRA_SQS_RECEIVE_BATCH_SIZE"
    )
    aira_sqs_visibility_timeout_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias="AIRA_SQS_VISIBILITY_TIMEOUT_SECONDS",
    )
    aira_worker_heartbeat_seconds: float = Field(
        default=60.0, gt=0, validation_alias="AIRA_WORKER_HEARTBEAT_SECONDS"
    )
    aira_worker_job_lease_seconds: int = Field(
        default=900, ge=1, validation_alias="AIRA_WORKER_JOB_LEASE_SECONDS"
    )
    aira_worker_concurrency: int = Field(
        default=4, ge=1, le=64, validation_alias="AIRA_WORKER_CONCURRENCY"
    )
    aira_dispatcher_batch_size: int = Field(
        default=10, ge=1, le=100, validation_alias="AIRA_DISPATCHER_BATCH_SIZE"
    )
    aira_dispatcher_lease_seconds: int = Field(
        default=30, ge=1, validation_alias="AIRA_DISPATCHER_LEASE_SECONDS"
    )
    aira_sqs_connect_timeout_seconds: float = Field(
        default=3.0, gt=0, validation_alias="AIRA_SQS_CONNECT_TIMEOUT_SECONDS"
    )
    aira_sqs_read_timeout_seconds: float = Field(
        default=25.0, gt=0, validation_alias="AIRA_SQS_READ_TIMEOUT_SECONDS"
    )
    aira_sqs_max_attempts: int = Field(
        default=3, ge=1, le=10, validation_alias="AIRA_SQS_MAX_ATTEMPTS"
    )

    # Hosted human identity. Empty issuer/client keeps Version 2 independent of OIDC.
    aira_oidc_issuer: str = Field(default="", validation_alias="AIRA_OIDC_ISSUER")
    aira_oidc_client_id: str = Field(
        default="", validation_alias="AIRA_OIDC_CLIENT_ID"
    )
    aira_oidc_token_use: str = Field(
        default="access", validation_alias="AIRA_OIDC_TOKEN_USE"
    )
    aira_oidc_jwks_url: str = Field(
        default="", validation_alias="AIRA_OIDC_JWKS_URL"
    )
    aira_oidc_algorithms: str = Field(
        default="RS256", validation_alias="AIRA_OIDC_ALGORITHMS"
    )
    aira_oidc_leeway_seconds: int = Field(
        default=30, validation_alias="AIRA_OIDC_LEEWAY_SECONDS"
    )
    aira_oidc_jwks_cache_seconds: int = Field(
        default=300, validation_alias="AIRA_OIDC_JWKS_CACHE_SECONDS"
    )
    aira_oidc_http_timeout_seconds: float = Field(
        default=3.0, validation_alias="AIRA_OIDC_HTTP_TIMEOUT_SECONDS"
    )

    triage_audit_jsonl: str = Field(default="", validation_alias="TRIAGE_AUDIT_JSONL")
    triage_audit_disable: str = Field(default="", validation_alias="TRIAGE_AUDIT_DISABLE")
    triage_audit_max_rag_chars: str = Field(default="200000", validation_alias="TRIAGE_AUDIT_MAX_RAG_CHARS")

    triage_metrics_log_disable: str = Field(default="", validation_alias="TRIAGE_METRICS_LOG_DISABLE")

    n8n_workflow_log_jsonl: str = Field(default="", validation_alias="N8N_WORKFLOW_LOG_JSONL")
    n8n_triage_feedback_jsonl: str = Field(default="", validation_alias="N8N_TRIAGE_FEEDBACK_JSONL")
    n8n_workflow_log_disable: str = Field(default="", validation_alias="N8N_WORKFLOW_LOG_DISABLE")
    n8n_triage_feedback_disable: str = Field(default="", validation_alias="N8N_TRIAGE_FEEDBACK_DISABLE")

    @field_validator("admin_upload_max_bytes", mode="before")
    @classmethod
    def _admin_upload_max_bytes(cls, v: Any) -> int:
        if v is None or v == "":
            return 5_242_880
        return int(v)

    @field_validator("aira_data_mode", mode="before")
    @classmethod
    def _aira_data_mode(cls, v: Any) -> str:
        s = "demo" if v is None or str(v).strip() == "" else str(v).strip().lower()
        if s not in ("demo", "user"):
            raise ValueError("AIRA_DATA_MODE must be 'demo' or 'user'")
        return s

    @field_validator("api_rate_limit_disabled", "rag_workspace_corpus_only", mode="before")
    @classmethod
    def _boolish(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if v is None or v == "":
            return False
        return str(v).lower() in ("1", "true", "yes", "on")

    @field_validator(
        "triage_audit_disable",
        "triage_metrics_log_disable",
        "n8n_workflow_log_disable",
        "n8n_triage_feedback_disable",
        mode="before",
    )
    @classmethod
    def _empty_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    def openai_base_url_optional(self) -> str | None:
        b = self.openai_api_base.strip()
        return b or None

    def resolve_llm_api_key(self) -> str:
        if self.openai_api_key.strip():
            return self.openai_api_key.strip()
        if self.openrouter_api_key.strip():
            return self.openrouter_api_key.strip()
        raise RuntimeError(
            "No API key found. Copy .env.example to .env in the project root and set "
            "OPENAI_API_KEY (or OPENROUTER_API_KEY)."
        )

    def gradio_enabled(self) -> bool:
        return self.enable_gradio_ui.strip().lower() not in ("0", "false", "no")


def _settings_env_keys() -> frozenset[str]:
    keys: set[str] = set()
    for finfo in Settings.model_fields.values():
        alias = finfo.validation_alias
        if isinstance(alias, str):
            keys.add(alias)
    return frozenset(keys)


def _merged_env_dict() -> dict[str, str]:
    """Dotenv + optional YAML + workspace overrides + process environment (env wins over overrides and YAML)."""
    root = project_root()
    load_dotenv(root / ".env", override=False)
    merged: dict[str, str] = {}
    yp = _yaml_path()
    if yp is not None:
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        if data is None:
            pass
        elif not isinstance(data, dict):
            raise ValueError(f"CONFIG_YAML {yp} must contain a mapping at the root, got {type(data).__name__}")
        else:
            merged.update(_flatten_yaml(data))
    # Resolve workspace path using CONFIG_YAML + env (same keys as final merge).
    effective: dict[str, str] = {**merged}
    for key in _settings_env_keys():
        val = os.environ.get(key)
        if val is not None and val != "":
            effective[key] = val
    ow = _operator_overrides_path(effective)
    if ow.is_file():
        raw_ow = yaml.safe_load(ow.read_text(encoding="utf-8"))
        if raw_ow is not None:
            if not isinstance(raw_ow, dict):
                raise ValueError(
                    f"operator_overrides {ow} must contain a mapping at the root, got {type(raw_ow).__name__}"
                )
            merged.update(_flatten_yaml(raw_ow))
    for key in _settings_env_keys():
        val = os.environ.get(key)
        if val is not None and val != "":
            merged[key] = val
    return merged


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings (call ``reset_settings()`` in tests after changing env)."""
    return Settings.model_validate(_merged_env_dict())


def reset_settings() -> None:
    """Clear the settings cache (use from tests when monkeypatching environment)."""
    get_settings.cache_clear()
