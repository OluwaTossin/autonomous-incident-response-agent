# Runbook: Disk / storage saturation (full filesystem, PVC, EBS)

**Runbook ID:** RB-DISK-SAT-006  
**Service:** Nodes, pods with **ephemeral** storage, **PVCs**, database volumes, log partitions  
**Environment:** Production  
**Primary owner:** Platform / SRE + **data owner** for stateful volumes  
**Supporting:** Application teams for log volume inside containers  
**Severity when triggered:** HIGH–CRITICAL (write failures → **cascading** outages, DB **read-only** mode, pod **evictions**)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**Disk full** or **inode exhaustion** causes writes to fail: logs stop, DBs may halt, Kubernetes may **evict** pods (`DiskPressure` on node), and backups may break. Goal: **free space safely**, identify growth source, and prevent recurrence (retention, sizing, alerts).

---

## Scope and applicability

**In scope:** Root `/`, `/var`, container **writable layer**, **emptyDir**, **PVC**, EBS/EFS utilisation, **inode** usage.

**Out of scope:** **Object storage** (S3) quotas — different procedures (lifecycle, bucket policy).

---

## Symptoms and typical alerts

- Alerts: `DiskSpaceLow`, `VolumeFull`, `KubeNodeDiskPressure`, database **cannot extend datafile**.
- `df -h` / cloud metrics: utilisation >85–90% sustained; `df -i` inode **100%**.
- Apps: `No space left on device`, write errors, WAL/archive failures.

---

## Preconditions

- [ ] **Which mount** (node vs pod vs PVC) — wrong target wastes time.  
- [ ] **Blast radius** — shared node pool vs dedicated DB instance.  
- [ ] **Change freeze** awareness — expanding EBS may need approval.

---

## Immediate checks (first 5 minutes)

1. **Node vs workload** — `kubectl describe node` for `DiskPressure`? Or only one PVC?  
2. **Growth rate** — Sudden spike (bad log loop, core dump) vs slow creep (retention gap)?  
3. **Critical services** — DB data dir, etcd (control plane — escalate immediately if applicable).  
4. **Read-only remediation** — Some DBs go read-only when full — **do not** delete data blindly.

---

## Deeper diagnosis (15–30 minutes)

| Source | Investigation |
|--------|----------------|
| **Logs** | App log rotation missing; debug logging; single huge file. |
| **Container layer** | Writes to local disk instead of object store; crash dumps accumulating. |
| **PVC / EBS** | Autoscaling disabled; wrong gp2/gp3 sizing; snapshot backlog. |
| **Package/cache** | Image build residue, `apt` cache in long-lived VMs (less common in containers). |
| **Inodes** | Millions of tiny files (temp, metrics shards). |

Use **largest directory** tools appropriate to the environment (`ncdu`, cloud console volume metrics, CSI metrics).

---

## Likely root causes

1. **Retention** not applied (logs, metrics, traces).  
2. **Traffic** or error storm generating huge logs.  
3. **Undersized** volume for legitimate growth.  
4. **Bug** writing unbounded local files.  
5. **Backup/snapshot** staging on same volume.

---

## Recommended remediation (ordered)

1. **Approve safe deletes:** rotate/truncate **non-critical** logs per policy; move data to object storage if architecture allows.  
2. **Expand volume** (EBS resize, PVC expansion if StorageClass allows) — **planned** with DBA for databases.  
3. **Evacuate workloads** from `DiskPressure` nodes after cordon — reschedule carefully.  
4. **Fix application** — stop runaway logging; write to bounded buffer or remote log.  
5. **Alerts** at 70/80% and **inode** alerts where relevant.

---

## Escalation criteria

- **Database** data volume — **DBA required** before destructive cleanup.  
- **etcd / control plane** — immediate platform escalation.  
- **Legal hold** or **compliance** data — no delete without compliance sign-off.

---

## Communication and status updates

Disk incidents can cause **silent** degradation — state **which systems** cannot write and **ETA** for expansion or cleanup.

---

## Recovery verification

- [ ] Utilisation **below** warning threshold with **sustained** headroom (not just one `rm`).  
- [ ] Inodes **below** critical threshold.  
- [ ] No `DiskPressure` on affected nodes; DB read/write healthy.

---

## Post-incident

- [ ] **Retention policies** automated (log shipper, DB maintenance).  
- [ ] Right-size volumes; add **growth** dashboards.  
- [ ] Postmortem if customer data or transactions affected.

---

## Evidence to capture

Before/after `df`, volume IDs, largest paths (redacted filenames if sensitive), incident timeline, approvals for deletion.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-DISK-SAT-006
service: nodes_pvc_databases
symptoms: [disk_full, disk_pressure, no_space_left_on_device, inode_exhaustion, pvc_full]
environments: [production]
tags: [storage, ebs, kubernetes, logging, retention]
related_runbooks: [runbook-05-kubernetes-crashloopbackoff, runbook-04-database-connection-exhaustion]
```
