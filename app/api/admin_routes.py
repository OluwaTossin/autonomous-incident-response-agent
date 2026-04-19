"""Admin-only workspace ingestion and reindex (Phase V2.7)."""

from __future__ import annotations

import argparse
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator
from slowapi import Limiter

from app.api.security import (
    admin_read_rate_limit_string,
    admin_reindex_rate_limit_string,
    admin_upload_rate_limit_string,
    require_admin_api_key,
)
from app.config import get_settings, reset_settings
from app.config.settings import _flatten_yaml
from app.rag.cli import cmd_build_index
from app.workspace.paths import project_root, workspace_config_dir, workspace_data_dir

_log = logging.getLogger(__name__)

_ALLOWED_CATEGORIES = frozenset({"runbooks", "incidents", "logs", "knowledge_base"})
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$")

_reindex_lock = threading.Lock()
_reindex_state: dict[str, Any] = {
    "phase": "idle",
    "started_at": None,
    "finished_at": None,
    "message": "",
    "exit_code": None,
}


class AdminFileInfo(BaseModel):
    path: str
    size_bytes: int


class AdminFilesResponse(BaseModel):
    files: list[AdminFileInfo]


class AdminUploadResponse(BaseModel):
    path: str
    size_bytes: int


class AdminReindexResponse(BaseModel):
    status: Literal["completed", "failed"]
    message: str


class AdminIndexStatusResponse(BaseModel):
    phase: str
    started_at: str | None = None
    finished_at: str | None = None
    message: str = ""
    exit_code: int | None = None


class OperatorSettingsPatch(BaseModel):
    """Persisted to ``workspaces/<id>/config/operator_overrides.yaml`` (precedence below process env)."""

    model_config = ConfigDict(extra="forbid")

    aira_data_mode: Literal["demo", "user"] | None = None
    rag_top_k: int | None = Field(None, ge=1, le=64)
    llm_temperature: float | None = Field(None, ge=0.0, le=2.0)
    llm_model: str | None = Field(None, min_length=1, max_length=120)
    embedding_model: str | None = Field(None, min_length=1, max_length=120)
    rag_workspace_corpus_only: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> OperatorSettingsPatch:
        fields = (
            self.aira_data_mode,
            self.rag_top_k,
            self.llm_temperature,
            self.llm_model,
            self.embedding_model,
            self.rag_workspace_corpus_only,
        )
        if all(v is None for v in fields):
            raise ValueError("At least one setting must be provided")
        return self


class OperatorSettingsPatchResponse(BaseModel):
    status: Literal["updated"]
    path: str
    updated_keys: list[str]


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).replace(microsecond=0).isoformat()


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not base or base != name or ".." in name or "/" in name or "\\" in name:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_filename", "message": "Use a plain file name only."},
        )
    if not _SAFE_NAME_RE.match(base):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_filename",
                "message": "Filename must match ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$",
            },
        )
    return base


def _allowed_upload_suffix(name: str) -> None:
    lower = name.lower()
    ok = lower.endswith((".md", ".markdown", ".txt", ".log", ".yaml", ".yml"))
    if not ok:
        raise HTTPException(
            status_code=415,
            detail={"error": "unsupported_type", "message": "Allowed: .md .markdown .txt .log .yaml .yml"},
        )


def _list_workspace_files() -> list[AdminFileInfo]:
    root = workspace_data_dir()
    if not root.is_dir():
        return []
    out: list[AdminFileInfo] = []
    for sub in sorted(_ALLOWED_CATEGORIES):
        d = root / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            out.append(AdminFileInfo(path=rel, size_bytes=path.stat().st_size))
    return out


def _execute_reindex() -> tuple[int, str]:
    args = argparse.Namespace(root="", out="", chunk_size=900, chunk_overlap=150, batch_size=64)
    code = cmd_build_index(args)
    if code != 0:
        return code, "Index build reported failure (see server logs)."
    return 0, "Index rebuilt successfully."


def _load_operator_overrides_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}
    return _flatten_yaml(raw)


def _write_operator_overrides(path: Path, flat: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Human-readable keys (already UPPER_SNAKE from _flatten_yaml).
    ordered = {k: flat[k] for k in sorted(flat)}
    tmp.write_text(yaml.safe_dump(ordered, default_flow_style=False, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def build_admin_router(limiter: Limiter) -> APIRouter:
    """Build ``/admin/*`` routes with shared rate limiter (call from ``main`` after limiter exists)."""
    r = APIRouter(prefix="/admin", tags=["admin"])

    @r.get("/files", response_model=AdminFilesResponse)
    @limiter.limit(admin_read_rate_limit_string())
    def admin_list_files(
        request: Request,
        _admin: None = Depends(require_admin_api_key),
    ) -> AdminFilesResponse:
        """List corpus files under the active workspace ``data/`` (relative paths)."""
        return AdminFilesResponse(files=_list_workspace_files())

    @r.post("/upload", response_model=AdminUploadResponse)
    @limiter.limit(admin_upload_rate_limit_string())
    async def admin_upload(
        request: Request,
        category: str = Form(..., description="runbooks | incidents | logs | knowledge_base"),
        file: UploadFile = File(...),
        _admin: None = Depends(require_admin_api_key),
    ) -> AdminUploadResponse:
        """Upload one text file into ``workspaces/<id>/data/<category>/``."""
        cat = category.strip().lower()
        if cat not in _ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_category",
                    "message": f"category must be one of: {sorted(_ALLOWED_CATEGORIES)}",
                },
            )
        name = _safe_filename(file.filename or "")
        _allowed_upload_suffix(name)

        max_bytes = get_settings().admin_upload_max_bytes
        dest_dir = workspace_data_dir() / cat
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name

        size = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with tmp.open("wb") as fh:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail={"error": "payload_too_large", "message": f"Max upload is {max_bytes} bytes"},
                        )
                    fh.write(chunk)
            tmp.replace(dest)
        except HTTPException:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
        except OSError as e:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            _log.warning("admin upload failed: %s", e)
            raise HTTPException(status_code=500, detail={"error": "write_failed", "message": str(e)}) from e
        finally:
            await file.close()

        rel = dest.relative_to(workspace_data_dir()).as_posix()
        return AdminUploadResponse(path=rel, size_bytes=size)

    @r.post("/reindex", response_model=AdminReindexResponse)
    @limiter.limit(admin_reindex_rate_limit_string())
    def admin_reindex(
        request: Request,
        _admin: None = Depends(require_admin_api_key),
    ) -> AdminReindexResponse:
        """Rebuild the FAISS index (synchronous; may take minutes)."""
        if not _reindex_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail={"error": "reindex_in_progress", "message": "Another reindex is already running."},
            )
        try:
            _reindex_state["phase"] = "running"
            _reindex_state["started_at"] = time.time()
            _reindex_state["finished_at"] = None
            _reindex_state["exit_code"] = None
            _reindex_state["message"] = "Running index build…"
            try:
                code, msg = _execute_reindex()
            except Exception as e:
                _log.exception("admin reindex failed")
                _reindex_state["phase"] = "error"
                _reindex_state["message"] = str(e)
                _reindex_state["exit_code"] = 1
                _reindex_state["finished_at"] = time.time()
                raise HTTPException(
                    status_code=500,
                    detail={"error": "reindex_failed", "message": str(e)},
                ) from e
            _reindex_state["exit_code"] = code
            _reindex_state["message"] = msg
            _reindex_state["phase"] = "success" if code == 0 else "error"
            _reindex_state["finished_at"] = time.time()
            if code != 0:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "reindex_failed", "message": msg, "exit_code": code},
                )
            return AdminReindexResponse(status="completed", message=msg)
        finally:
            _reindex_lock.release()

    @r.get("/index-status", response_model=AdminIndexStatusResponse)
    @limiter.limit(admin_read_rate_limit_string())
    def admin_index_status(
        request: Request,
        _admin: None = Depends(require_admin_api_key),
    ) -> AdminIndexStatusResponse:
        """Last reindex outcome (in-process state; accurate for single worker)."""
        return AdminIndexStatusResponse(
            phase=str(_reindex_state.get("phase", "idle")),
            started_at=_iso_utc(_reindex_state.get("started_at")),
            finished_at=_iso_utc(_reindex_state.get("finished_at")),
            message=str(_reindex_state.get("message", "")),
            exit_code=_reindex_state.get("exit_code"),
        )

    @r.patch("/operator-settings", response_model=OperatorSettingsPatchResponse)
    @limiter.limit(admin_upload_rate_limit_string())
    def admin_patch_operator_settings(
        request: Request,
        body: OperatorSettingsPatch,
        _admin: None = Depends(require_admin_api_key),
    ) -> OperatorSettingsPatchResponse:
        """Merge allowlisted keys into workspace ``config/operator_overrides.yaml`` (env still wins)."""
        path = workspace_config_dir() / "operator_overrides.yaml"
        current = _load_operator_overrides_map(path)
        updated_keys: list[str] = []
        if body.aira_data_mode is not None:
            current["AIRA_DATA_MODE"] = body.aira_data_mode
            updated_keys.append("AIRA_DATA_MODE")
        if body.rag_top_k is not None:
            current["RAG_TOP_K"] = str(body.rag_top_k)
            updated_keys.append("RAG_TOP_K")
        if body.llm_temperature is not None:
            current["LLM_TEMPERATURE"] = str(body.llm_temperature)
            updated_keys.append("LLM_TEMPERATURE")
        if body.llm_model is not None:
            current["LLM_MODEL"] = body.llm_model.strip()
            updated_keys.append("LLM_MODEL")
        if body.embedding_model is not None:
            current["EMBEDDING_MODEL"] = body.embedding_model.strip()
            updated_keys.append("EMBEDDING_MODEL")
        if body.rag_workspace_corpus_only is not None:
            current["RAG_WORKSPACE_ONLY"] = "1" if body.rag_workspace_corpus_only else "0"
            updated_keys.append("RAG_WORKSPACE_ONLY")
        try:
            _write_operator_overrides(path, current)
        except OSError as e:
            _log.warning("operator-settings write failed: %s", e)
            raise HTTPException(
                status_code=500,
                detail={"error": "write_failed", "message": str(e)},
            ) from e
        reset_settings()
        try:
            rel = path.resolve().relative_to(project_root()).as_posix()
        except ValueError:
            rel = path.resolve().as_posix()
        return OperatorSettingsPatchResponse(status="updated", path=rel, updated_keys=updated_keys)

    return r
