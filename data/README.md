# Data directory

Phase 2 **operational knowledge** and **sample telemetry** for RAG and evaluation (see root `README.md` for phase status).

## Layout

| Subfolder | Role |
|-----------|------|
| **`runbooks/`** | SRE procedural corpus (`RB-*`); primary retrieval source alongside incidents and logs. |
| **`incidents/`** | Synthetic incident postmortems (`incident-*.md`) + `sample-incident.md`. |
| **`logs/`** | Synthetic `.log` bundles + `sample-log.md`. |
| **`knowledge_base/`** | Supplementary ops docs (escalation, ownership, dependency tiers, first-response checklist). |

## Inventory

- **Runbooks** (procedures): `data/runbooks/*.md` — **11** files  
- **Incidents:** `data/incidents/incident-*.md` — **20** files (+ `sample-incident.md`)  
- **Logs:** `data/logs/*.log` — **21** files (+ `sample-log.md`)  
- **Knowledge base:** `data/knowledge_base/*.md` — **5** files (README + 4 guides)

## Phase 3 loaders

Suggested globs from repo root:

- `data/runbooks/**/*.md`
- `data/incidents/incident-*.md`
- `data/logs/*.log`
- `data/knowledge_base/**/*.md`
