import { ApiFailure } from "./api-errors";
import { triageJsonHeaders } from "./api";

export type OperatorConfig = {
  workspace_id: string;
  workspaces_root: string;
  aira_data_mode: string;
  rag_top_k: number;
  llm_model: string;
  llm_temperature: number;
  embedding_model: string;
  rag_workspace_corpus_only: boolean;
  rag_corpus_root_configured: boolean;
  workspace_data_dir: string;
  workspace_index_dir: string;
  operator_overrides_file: string;
  operator_overrides_active: boolean;
  admin_routes_enabled: boolean;
  triage_api_key_configured: boolean;
  gradio_ui_enabled: boolean;
};

function formatDetail(data: unknown): string {
  if (!data || typeof data !== "object") return "Request failed";
  const d = data as Record<string, unknown>;
  const detail = d.detail;
  if (typeof detail === "string") return detail;
  return JSON.stringify(data);
}

export async function getOperatorConfig(baseUrl: string): Promise<OperatorConfig> {
  const r = await fetch(`${baseUrl}/operator-config`, { headers: triageJsonHeaders() });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /operator-config", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  return data as OperatorConfig;
}
