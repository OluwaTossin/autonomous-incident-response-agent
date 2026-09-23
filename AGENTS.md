# AIRA Codex Instructions

## Project

AIRA is the Autonomous DevOps Incident Response Agent.

This working tree is the active Version 3 development environment.

The project evolved through:

- Version 1: end-to-end capstone / production-shaped proof of concept
- Version 2: reusable self-hosted BYOD product
- Version 3: hosted multi-user platform and automated operational integrations

## Reference worktrees

Two historical worktrees exist beside this repository:

- ../aira-v1
- ../aira-v2

They are READ-ONLY references.

Do not edit, commit, format, migrate, or otherwise modify files in those worktrees.

All implementation changes belong in this Version 3 working tree.

## How to use the historical versions

Version 1 should be consulted for:
- original architecture
- AWS ECS/Fargate deployment
- Terraform infrastructure
- CloudWatch observability
- CI/CD
- n8n workflow design
- original RAG / LangGraph behavior

Version 2 should be the primary behavioral baseline.

Consult it for:
- BYOD workspaces
- workspace-scoped RAG
- demo vs user data mode
- product configuration
- user-supplied runbooks, logs, incidents, and knowledge-base files
- admin ingestion/reindexing APIs
- Next.js Setup / Configuration / Triage interfaces
- product Docker Compose flow
- product CLI commands
- security defaults and documentation

## Existing documentation to read before designing Version 3

Start with:

- README.md
- docs/README.md
- docs/build-journey/execution-v1.md
- docs/architecture/
- docs/installation.md
- docs/configuration.md
- docs/bring-your-own-data.md
- docs/reindexing.md
- docs/security.md
- docs/troubleshooting.md
- frontend/README.md
- infra/terraform/
- workflows/n8n/
- pyproject.toml
- docker-compose.yml
- .github/workflows/

Inspect the implementation under:

- app/api/
- app/agent/
- app/rag/
- app/config/
- app/models/
- frontend/
- workspaces/
- sample_data/

## Version 3 objective

Version 3 evolves AIRA from a self-hosted single-operator BYOD tool into a hosted platform.

The broad product direction includes:

- authentication
- users
- organizations / workspaces
- tenant isolation
- persistent application data
- hosted API
- per-workspace knowledge
- per-workspace vector/search isolation
- usage tracking
- per-user or per-workspace rate limiting
- cloud-native ingestion
- monitoring/logging integrations
- automated alert ingestion
- automatic incident enrichment
- preserving human review for consequential actions

The eventual operational flow should evolve from:

manual upload -> manual triage

toward:

alert -> automatic context collection -> retrieval -> triage -> evidence ->
operator review -> optional workflow action

## Engineering principles

- Preserve Version 2 behavior unless a Version 3 requirement explicitly changes it.
- Evolve incrementally rather than rewriting working components without reason.
- Define tenant boundaries before implementing multi-tenancy.
- Security and tenant isolation are architectural requirements, not later polish.
- Never store secrets in source control.
- Never commit real customer or company operational data.
- Prefer explicit schemas and migrations.
- Keep reasoning output structured and auditable.
- Maintain evidence/citation behavior.
- Maintain triage_id or an equivalent correlation identifier.
- Update tests and documentation with architectural changes.
- Run relevant tests before reporting a task complete.
- Do not make AWS changes without first showing the Terraform plan or command and obtaining approval.
- Do not destroy AWS resources without explicit approval.

## Git workflow

- Active development branch: v3-hosted-platform
- Do not modify V1 or V2 tags/worktrees.
- Keep changes small and logically grouped.
- Before committing, show:
  - changed files
  - tests run
  - outstanding risks

## Initial instruction

Before implementing Version 3, inspect the repository and reference worktrees and produce an architecture assessment.

Do not begin coding until the Version 3 execution plan has been agreed.