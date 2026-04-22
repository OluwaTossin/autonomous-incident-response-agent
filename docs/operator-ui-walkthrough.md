# Operator UI walkthrough (demo order)

Use this when demoing the **Next.js operator console** (Triage, Setup, Configuration) against a running API — for example the static UI on **S3 website** or **CloudFront** plus an **ALB** URL shown at the top of each page.

## Where to start: Triage vs Setup vs Configuration

| Goal | Start here |
|------|------------|
| **Show “run an incident through the model”** with bundled samples and the index already in the API image | **Triage** (home) — no Setup required first. |
| **Show bring-your-own data**: upload files, rebuild index, then triage on new corpus | **Setup** first (admin key), then **Triage**. |
| **Show safe product tuning** (models, `AIRA_DATA_MODE`, RAG top‑k, etc.) without editing Python | **Configuration** (admin key for saves); optional before or after Triage. |

**Default demo path:** open the UI root (same as **Triage**), run a sample, walk through output → evidence → timeline → optional feedback. Add **Setup** / **Configuration** only if you want those chapters in the story.

---

## 1 · Triage (home)

**URL:** `/` on the static host (e.g. `…/index.html` or the bucket website root).

1. **Confirm the API line** under the title — it should be the **ALB** (or local) base URL your audience will hit; the browser calls this origin from the UI origin (CORS must allow the UI — see [`deploy/aws-ecs.md`](deploy/aws-ecs.md)).
2. **Incident input** — choose a **Sample** from the dropdown *or* paste your own JSON (same shape as the samples: `alert_title`, `service_name`, `environment`, `metrics` / `logs`, `time_of_occurrence`, etc.).
3. Click **Run triage** — wait for the request to finish (LLM + RAG can take tens of seconds).
4. **Triage output** — read structured fields (severity, summary, actions, `triage_id`, …).
5. **Evidence** — expand grouped snippets; tie back to “what the model saw” from retrieval.
6. **Timeline** — walk through the suggested ordering of events / checks.
7. **Feedback (optional)** — after a successful run, use **Yes/No** and notes, then **Submit feedback** (links to `triage_id`; same contract as Gradio / n8n).

**If `401` on Run triage:** the API has **`API_KEY`** set but the static bundle does not send **`x-api-key`**. For demos, either leave **`API_KEY`** unset on the ECS task, or rebuild the UI with **`NEXT_PUBLIC_TRIAGE_API_KEY`** matching the server key (demo-only; value is public) — see [`frontend/README.md`](../frontend/README.md) and [`security.md`](security.md).

---

## 2 · Setup (corpus & index)

**URL:** `/setup`.

Use this when you want to demo **ingestion** and **reindex**, not for every first-time “happy path” if the image already contains a good index.

1. Paste **`ADMIN_API_KEY`** (must match the value configured on the API) and click **Save to session** — stored in **`sessionStorage`** for this tab only; not baked into the static export.
2. **Upload** — pick category (`runbooks`, `incidents`, `logs`, `knowledge_base`), choose an allowed file (`.md`, `.log`, `.yaml`, … per [`security.md`](security.md)), upload.
3. **Rebuild index** — start a reindex; poll **index status** until complete so **Triage** uses the new FAISS bundle.
4. Return to **Triage** and run a scenario that should retrieve your new content (or a unique string you added).

If admin routes are disabled on the server (`ADMIN_API_KEY` unset in production mode), Setup upload/reindex will not be available — say that in the demo and stay on **Triage** + pre-baked index.

---

## 3 · Configuration (read + safe overrides)

**URL:** `/configuration`.

1. The page loads **effective config** from **`GET /operator-config`** (uses **`API_KEY`** / `x-api-key` when the server requires it — optional **`NEXT_PUBLIC_TRIAGE_API_KEY`** at build time, same caveat as Triage).
2. Adjust allowlisted fields (e.g. **`AIRA_DATA_MODE`**, models, **`top_k`**) if exposed; **Save** sends **`PATCH /admin/operator-settings`** and needs the **admin** key (paste again or already in session from Setup).
3. Explain precedence: env / secrets still win for true secrets; overrides go to workspace `config/operator_overrides.yaml` — see [`configuration.md`](configuration.md).

Use **Configuration** after **Setup** if you changed mode or retrieval and want the audience to see it reflected before triage.

---

## Suggested demo scripts (short)

**A — Five minutes (model + RAG story)**  
Triage → sample → Run triage → output → evidence → done.

**B — Ten minutes (product story)**  
Triage (A) → Setup (upload one small `.md`, reindex) → Triage again with a prompt that hits the new doc → Configuration (show read-only + one safe toggle) → Triage.

**C — Security-aware**  
Mention two keys (**admin** vs **triage**), session-only admin key, why **`NEXT_PUBLIC_TRIAGE_API_KEY`** is optional and demo-only — [`security.md`](security.md).

---

## See also

- [`installation.md`](installation.md) — local Compose path (same UI patterns).  
- [`bring-your-own-data.md`](bring-your-own-data.md) — workspace layout behind Setup.  
- [`reindexing.md`](reindexing.md) — when to rebuild the index.  
- [`frontend/README.md`](../frontend/README.md) — build-time env vars for deployed static UI.
