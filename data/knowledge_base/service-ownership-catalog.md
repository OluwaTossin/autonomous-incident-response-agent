# Service ownership catalog (sample)

Fictional map for RAG: **service → team → primary runbook IDs**.

| Service | Team | Runbook hints (`RB-*`) |
|---------|------|-------------------------|
| `payment-api` | payments | `RB-PAYMENT-API-HIGH-CPU-001`, `RB-HTTP-5XX-003` |
| `orders-api` | commerce | `RB-GEN-HIGH-CPU-001`, `RB-DB-CONN-004` |
| `cart-api` | commerce | `RB-DB-CONN-004`, `RB-HTTP-5XX-003` |
| `auth-service` | platform | `RB-K8S-CRASH-005`, `RB-TLS-CERT-007` |
| `bff-api` | platform | `RB-K8S-CRASH-005` |
| `ledger-service` | payments | `RB-HTTP-5XX-003`, internal mTLS docs |
| `notifications-api` | messaging | `RB-MEM-OOM-002`, `RB-QUEUE-LAG-009` |
| `search-indexer` | search | `RB-MEM-OOM-002`, `RB-QUEUE-LAG-009` |
| `reports-worker` | data | `RB-QUEUE-LAG-009`, `RB-DB-CONN-004` |
| `inventory-api` | catalog | `RB-DISK-SAT-006`, `RB-GEN-HIGH-CPU-001` |
| `public-api` / edge | platform | `RB-LB-HEALTH-010`, `RB-TLS-CERT-007` |
| External fraud API | integrations | `RB-EXT-API-008` |

## Notes

- **Tier-0** services (payments writer, auth IdP) require faster escalation; see `escalation-matrix-sample.md`.  
- This catalog is **not** authoritative for production; it mirrors synthetic incidents in `data/incidents/`.
