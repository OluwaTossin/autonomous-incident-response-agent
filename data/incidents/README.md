# `data/incidents/`

Synthetic **postmortem-style** incident records (`INC-001`–`INC-020`) plus [`sample-incident.md`](sample-incident.md) (template and catalog).

## Contents

- **`incident-NN-*.md`** — Scenario write-ups with timelines, impact, root cause, and **`RB-*`** runbook links (paths point to `data/runbooks/`).
- **`sample-incident.md`** — Structure template, runbook ID table, optional JSON block for eval harnesses.

## Phase 3 ingestion

Index `data/incidents/incident-*.md` for gold narratives; include or exclude `sample-incident.md` depending on whether you want the template in the vector store.

## Related

- Runbooks: [`../runbooks/`](../runbooks/)
- Logs: [`../logs/`](../logs/)
- Knowledge base: [`../knowledge_base/`](../knowledge_base/)
