"""Read-only operator config (triage key) for Next.js console (Phase V2.8)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter

from app.api.security import require_api_key_if_configured, triage_rate_limit_provider
from app.config import get_settings
from app.workspace.paths import project_root, workspace_config_dir, workspace_data_dir, workspace_index_dir


def _rel_under_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root()).as_posix()
    except ValueError:
        return path.as_posix()


class OperatorConfigResponse(BaseModel):
    """Non-secret product snapshot for the operator UI."""

    workspace_id: str = Field(..., description="Active WORKSPACE_ID")
    workspaces_root: str
    aira_data_mode: str
    rag_top_k: int
    llm_model: str
    llm_temperature: float
    embedding_model: str
    rag_workspace_corpus_only: bool
    rag_corpus_root_configured: bool
    workspace_data_dir: str
    workspace_index_dir: str
    operator_overrides_file: str
    operator_overrides_active: bool
    admin_routes_enabled: bool
    triage_api_key_configured: bool
    gradio_ui_enabled: bool


def build_operator_router(limiter: Limiter) -> APIRouter:
    r = APIRouter(tags=["operator"])

    @r.get("/operator-config", response_model=OperatorConfigResponse)
    @limiter.limit(triage_rate_limit_provider)
    def get_operator_config(
        request: Request,
        _auth: None = Depends(require_api_key_if_configured),
    ) -> OperatorConfigResponse:
        s = get_settings()
        ow = workspace_config_dir() / "operator_overrides.yaml"
        return OperatorConfigResponse(
            workspace_id=s.workspace_id,
            workspaces_root=s.workspaces_root,
            aira_data_mode=s.aira_data_mode,
            rag_top_k=s.rag_top_k,
            llm_model=s.llm_model,
            llm_temperature=s.llm_temperature,
            embedding_model=s.embedding_model,
            rag_workspace_corpus_only=s.rag_workspace_corpus_only,
            rag_corpus_root_configured=bool(s.rag_corpus_root.strip()),
            workspace_data_dir=_rel_under_repo(workspace_data_dir()),
            workspace_index_dir=_rel_under_repo(workspace_index_dir()),
            operator_overrides_file=_rel_under_repo(ow),
            operator_overrides_active=ow.is_file(),
            admin_routes_enabled=bool(s.admin_api_key.strip()),
            triage_api_key_configured=bool(s.api_key.strip()),
            gradio_ui_enabled=s.gradio_enabled(),
        )

    return r
