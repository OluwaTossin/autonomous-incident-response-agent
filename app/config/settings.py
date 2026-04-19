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


class Settings(BaseModel):
    """Application settings: optional ``CONFIG_YAML``, then ``.env`` / process environment."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_base: str = Field(default="", validation_alias="OPENAI_API_BASE")
    embedding_model: str = Field(default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL")
    rag_index_dir: str = Field(default=".rag_index", validation_alias="RAG_INDEX_DIR")

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

    cors_origins: str = Field(default="", validation_alias="CORS_ORIGINS")
    enable_gradio_ui: str = Field(default="1", validation_alias="ENABLE_GRADIO_UI")

    aira_env: str = Field(default="local", validation_alias="AIRA_ENV")

    triage_audit_jsonl: str = Field(default="", validation_alias="TRIAGE_AUDIT_JSONL")
    triage_audit_disable: str = Field(default="", validation_alias="TRIAGE_AUDIT_DISABLE")
    triage_audit_max_rag_chars: str = Field(default="200000", validation_alias="TRIAGE_AUDIT_MAX_RAG_CHARS")

    triage_metrics_log_disable: str = Field(default="", validation_alias="TRIAGE_METRICS_LOG_DISABLE")

    n8n_workflow_log_jsonl: str = Field(default="", validation_alias="N8N_WORKFLOW_LOG_JSONL")
    n8n_triage_feedback_jsonl: str = Field(default="", validation_alias="N8N_TRIAGE_FEEDBACK_JSONL")
    n8n_workflow_log_disable: str = Field(default="", validation_alias="N8N_WORKFLOW_LOG_DISABLE")
    n8n_triage_feedback_disable: str = Field(default="", validation_alias="N8N_TRIAGE_FEEDBACK_DISABLE")

    @field_validator("api_rate_limit_disabled", mode="before")
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
    """Dotenv + optional YAML + process environment (env wins over YAML for each key)."""
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
