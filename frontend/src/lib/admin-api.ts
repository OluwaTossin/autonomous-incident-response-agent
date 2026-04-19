import { ApiFailure } from "./api-errors";
import { getSessionAdminApiKey, publicAdminProxyInjectsHeaders } from "./config";

function adminHeadersJson(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (!publicAdminProxyInjectsHeaders()) {
    const k = getSessionAdminApiKey();
    if (k) h["x-admin-api-key"] = k;
  }
  return h;
}

function adminHeadersMultipart(): Record<string, string> {
  const h: Record<string, string> = {};
  if (!publicAdminProxyInjectsHeaders()) {
    const k = getSessionAdminApiKey();
    if (k) h["x-admin-api-key"] = k;
  }
  return h;
}

function formatDetail(data: unknown): string {
  if (!data || typeof data !== "object") return "Request failed";
  const d = data as Record<string, unknown>;
  const detail = d.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const o = detail as Record<string, unknown>;
    if (typeof o.message === "string") return o.message;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (e && typeof e === "object" && "msg" in e) {
          return String((e as { msg?: string }).msg ?? e);
        }
        return JSON.stringify(e);
      })
      .join("; ");
  }
  return JSON.stringify(data);
}

export type AdminFileRow = { path: string; size_bytes: number };

export async function adminListFiles(baseUrl: string): Promise<AdminFileRow[]> {
  const r = await fetch(`${baseUrl}/admin/files`, { headers: adminHeadersMultipart() });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /admin/files", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  const files = (data as { files?: AdminFileRow[] }).files;
  if (!Array.isArray(files)) throw new ApiFailure("Malformed /admin/files response", "malformed_response", r.status);
  return files;
}

export async function adminUpload(
  baseUrl: string,
  category: string,
  file: File,
): Promise<{ path: string; size_bytes: number }> {
  const fd = new FormData();
  fd.append("category", category);
  fd.append("file", file);
  const r = await fetch(`${baseUrl}/admin/upload`, {
    method: "POST",
    headers: adminHeadersMultipart(),
    body: fd,
  });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /admin/upload", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  const path = (data as { path?: string }).path;
  const size_bytes = (data as { size_bytes?: number }).size_bytes;
  if (typeof path !== "string" || typeof size_bytes !== "number") {
    throw new ApiFailure("Malformed /admin/upload response", "malformed_response", r.status);
  }
  return { path, size_bytes };
}

export async function adminReindex(baseUrl: string): Promise<{ status: string; message: string }> {
  const r = await fetch(`${baseUrl}/admin/reindex`, {
    method: "POST",
    headers: adminHeadersJson(),
  });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /admin/reindex", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  return data as { status: string; message: string };
}

export type IndexStatus = {
  phase: string;
  started_at: string | null;
  finished_at: string | null;
  message: string;
  exit_code: number | null;
};

export async function adminIndexStatus(baseUrl: string): Promise<IndexStatus> {
  const r = await fetch(`${baseUrl}/admin/index-status`, { headers: adminHeadersMultipart() });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /admin/index-status", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  return data as IndexStatus;
}

export type OperatorSettingsPatch = {
  aira_data_mode?: "demo" | "user";
  rag_top_k?: number;
  llm_temperature?: number;
  llm_model?: string;
  embedding_model?: string;
  rag_workspace_corpus_only?: boolean;
};

export async function adminPatchOperatorSettings(
  baseUrl: string,
  patch: OperatorSettingsPatch,
): Promise<{ status: string; path: string; updated_keys: string[] }> {
  const r = await fetch(`${baseUrl}/admin/operator-settings`, {
    method: "PATCH",
    headers: adminHeadersJson(),
    body: JSON.stringify(patch),
  });
  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Invalid JSON from /admin/operator-settings", "invalid_json", r.status);
    }
  }
  if (!r.ok) throw new ApiFailure(formatDetail(data), "http", r.status);
  return data as { status: string; path: string; updated_keys: string[] };
}
