"""Workspace layout: single-tenant default ``default`` under ``workspaces/``."""

from app.workspace.paths import (
    workspace_config_dir,
    workspace_data_dir,
    workspace_index_dir,
    workspace_root,
)

__all__ = [
    "workspace_config_dir",
    "workspace_data_dir",
    "workspace_index_dir",
    "workspace_root",
]
