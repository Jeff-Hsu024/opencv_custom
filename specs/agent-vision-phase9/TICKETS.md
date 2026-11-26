# Phase 9 — Ticket set (PROPOSED)
Parent SPEC SHA-256: 8d662c69b50ba86c61c25007561ee67f95cf87280f11a6d1b3a171d887de06de (UTF-8, LF-normalized).
Local tracker: .scratch/agent-vision-phase9/issues. No external issue publication or dispatch. One Orca project, one feature worktree. Serialize overlapping edits; logical independence is not permission for concurrent writes.

| Ticket | Title | Blocked by | Use cases | SPEC | Acceptance |
|---|---|---|---|---|---|
| [MD-01](../../.scratch/agent-vision-phase9/issues/01-explicit-device-discovery.md) | Explicit Android discovery and target validation | None | UC01,UC08,UC09 | R01,R09 | A01 |
| [MD-02](../../.scratch/agent-vision-phase9/issues/02-atomic-frame-index.md) | Shared Store metadata and protected frame transactions | None | UC13,UC14 | R07,R09 | A06,A09 |
| [MD-03](../../.scratch/agent-vision-phase9/issues/03-expand-device-coordinator.md) | Expand cross-process execution coordinator | MD-02 | UC08,UC11,UC13 | R06,R07 | A06,A08 |
| [MD-04](../../.scratch/agent-vision-phase9/issues/04-migrate-observation-recorder.md) | Migrate primitive, Recorder and Transition entrypoints | MD-01, MD-03 | UC01,UC08,UC09,UC11,UC13 | R01,R06,R07,R09 | A01,A06,A08 |
| [MD-05](../../.scratch/agent-vision-phase9/issues/05-migrate-runtime-recovery.md) | Migrate legacy Runtime and Recovery | MD-04 | UC08,UC09,UC11,UC14 | R06,R07,R09 | A06,A08,A09 |
| [MD-06](../../.scratch/agent-vision-phase9/issues/06-migrate-registry-orchestrator.md) | Migrate registry and legacy task admission | MD-05 | UC08,UC11,UC12,UC13,UC14 | R05,R06,R07,R09 | A05,A06,A08,A09 |
| [MD-07](../../.scratch/agent-vision-phase9/issues/07-contract-parallel-execution.md) | Contract: enable per-device concurrency | MD-06 | UC07,UC08,UC11,UC13,UC14 | R07,R09 | A06,A08,A09 |
| [MD-08](../../.scratch/agent-vision-phase9/issues/08-portable-publication.md) | Publish portable revision from proven learning | MD-01, MD-02 | UC02,UC03,UC14 | R02,R09 | A02,A09 |
| [MD-09](../../.scratch/agent-vision-phase9/issues/09-portable-preflight.md) | Read-only preflight on compatible device B | MD-07, MD-08 | UC04,UC09 | R03,R07,R09 | A03 |
| [MD-10](../../.scratch/agent-vision-phase9/issues/10-portable-trial-runtime.md) | Explicit qualification trial on target device | MD-09 | UC05,UC09,UC11 | R04,R06,R07,R09 | A04,A08 |
| [MD-11](../../.scratch/agent-vision-phase9/issues/11-qualification-enrollment.md) | Commit and revoke device qualifications | MD-10 | UC05,UC09,UC12 | R04,R05,R09 | A04,A05 |
| [MD-12](../../.scratch/agent-vision-phase9/issues/12-portable-family-single-execute.md) | Activate portable revision and run on qualified serial | MD-11 | UC06,UC09,UC11,UC12,UC14 | R05,R06,R09 | A05,A08,A09 |
| [MD-13](../../.scratch/agent-vision-phase9/issues/13-bounded-batch.md) | Bounded parallel batch and durable child receipts | MD-12 | UC07,UC10,UC11,UC13 | R07,R08,R09 | A06,A07,A08 |
| [MD-14](../../.scratch/agent-vision-phase9/issues/14-compatibility-agent-contract.md) | Compatibility and agent-facing release contract | MD-13 | UC01–UC14 | R01–R09 | A09 |
| [MD-15](../../.scratch/agent-vision-phase9/issues/15-independent-two-device-qualification.md) | Independent two-device E2E and raw audit | MD-14 | UC01–UC14 | R01–R09 | A01–A10 |

Initial frontier MD-01 and MD-02. MD-02–07 expand–migrate–contract; MD-08 may follow MD-01/02. MD-09 joins both paths. MD-10–15 deliver trial, qualification, single execute, batch, compatibility and independent acceptance. Confirm granularity, dependency edges and design decisions before dispatch.
