# Phase 9 - Revised ticket set
Status: REVIEW_RESOLVED_DESIGN, no dispatch. Supersedes original 15 MD tickets (Git planning commit d53b986). Contract v1 and exact SHA-256 values in ticket-manifest.json. Initial frontier C00 only. 24 tickets, expanded from review proposal 21 by splitting evidence snapshot vs legacy registry, shared interpreter vs proof resolution, and portable family vs single execute. One Orca project/worktree; logical independence is not permission for concurrent writes.

| Ticket | Title | Blocked by | Findings |
|---|---|---|---|
| [C00](../../.scratch/agent-vision-phase9/issues/C00-contract-freeze.md) | Contract fixture freeze | None | F01-F07 |
| [C01](../../.scratch/agent-vision-phase9/issues/C01-strict-discovery.md) | Strict Android discovery | C00 | F07 |
| [C02](../../.scratch/agent-vision-phase9/issues/C02-frame-store-transactions.md) | Frame index transactions and active pins | C00 | F06 |
| [C03](../../.scratch/agent-vision-phase9/issues/C03-asset-revisions.md) | Immutable scoped asset revisions | C02 | F01,F06 |
| [C04](../../.scratch/agent-vision-phase9/issues/C04-execution-coordinator.md) | Device and request owner coordinator | C02 | F05 |
| [C05](../../.scratch/agent-vision-phase9/issues/C05-device-action-epoch.md) | Durable Device Action Epoch | C01, C04 | F02 |
| [C06](../../.scratch/agent-vision-phase9/issues/C06-primitive-recorder-migration.md) | Primitive and Recorder migration | C03, C05 | F01,F02,F05 |
| [C07](../../.scratch/agent-vision-phase9/issues/C07-transition-migration.md) | Recorded Transition migration | C06 | F01,F02,F05 |
| [C08](../../.scratch/agent-vision-phase9/issues/C08-legacy-runtime-recovery.md) | Legacy Runtime and Recovery migration | C07 | F02,F05 |
| [C09](../../.scratch/agent-vision-phase9/issues/C09-evidence-snapshot.md) | Evidence snapshot and publication seal | C08 | F06 |
| [C10](../../.scratch/agent-vision-phase9/issues/C10-legacy-registry-admission.md) | Legacy registry and task admission | C09 | F05,F07 |
| [C11](../../.scratch/agent-vision-phase9/issues/C11-contract-parallel-execution.md) | Contract old gate and verify device overlap | C10 | F02,F05,F06,F07 |
| [P01](../../.scratch/agent-vision-phase9/issues/P01-definition-proof-seam.md) | Immutable definition resolver and proof verifier | C11 | F03,F06 |
| [P02](../../.scratch/agent-vision-phase9/issues/P02-shared-interpreter.md) | Shared target-bound deterministic interpreter | P01 | F02,F03 |
| [P03](../../.scratch/agent-vision-phase9/issues/P03-portable-publication.md) | Publish proven portable definition | P02 | F03,F06 |
| [P04](../../.scratch/agent-vision-phase9/issues/P04-portable-preflight.md) | Read-only portable preflight | P03 | F04,F07 |
| [P05](../../.scratch/agent-vision-phase9/issues/P05-qualification-trial.md) | Explicit target-device trial | P04 | F02,F03,F05 |
| [P06](../../.scratch/agent-vision-phase9/issues/P06-qualification-slots.md) | Per-device Qualification Slot CAS | P05 | F04,F05 |
| [P07](../../.scratch/agent-vision-phase9/issues/P07-portable-family-registry.md) | Portable family revision registry | P06 | F04,F06 |
| [P08](../../.scratch/agent-vision-phase9/issues/P08-portable-single-execute.md) | Pinned single-device portable execution | P07 | F02,F03,F04,F05 |
| [B01](../../.scratch/agent-vision-phase9/issues/B01-atomic-batch-admission.md) | Atomic parent admission and child reservations | P08 | F04,F05 |
| [B02](../../.scratch/agent-vision-phase9/issues/B02-parallel-batch-reconcile.md) | Bounded parallel execution and reconciliation | B01 | F05 |
| [V01](../../.scratch/agent-vision-phase9/issues/V01-compatibility-verification.md) | Compatibility and frozen store verification | B02 | F01-F07 |
| [V02](../../.scratch/agent-vision-phase9/issues/V02-independent-live-qualification.md) | Independent two-device qualification | V01 | F01-F07 |

C00 verifies/finalizes executable contract fixtures before code. C01-C11 expand/migrate/contract; P01-P08 portable; B01-B02 admission/execute; V01-V02 compatibility/live qualification. No implementation, external issues, or DAG started.
