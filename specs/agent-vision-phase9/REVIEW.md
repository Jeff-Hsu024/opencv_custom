# Phase 9 — Design and ticket review

Review target: d53b98648a61572520b0170529b61a6e8b16b703.
Baseline source: bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb.
Verdict: REQUIRES_REVISION_BEFORE_DISPATCH.
This is an in-context design/code inspection, not an independent EGM review, implementation, regression run or live device qualification. SPEC and proposed tickets are not approved for dispatch.

## Findings
F01 HIGH — Named asset publication and scope. R07/MD-02 describe frame/index transactions but not the two-file named AssetRegistry publication (assets.py register_from_frame, lines 176–208), and Recorder._asset (recorder.py) resolves global names and retains the corresponding PNG. Different devices registering the same label can race, overwrite a template, or pair metadata with the wrong bytes. Define immutable asset revisions, device/session-scoped resolution for new paths, transaction/snapshot for metadata + PNG + retained digest. Preserve legacy named API and document collision behavior; do not silently rewrite existing assets. Acceptance: two processes publish same name for different devices, consume the exact intended revision, crash between publication stages; wrong device fails before input, prior evidence hashes unchanged.

F02 HIGH — Same-device time-of-check/time-of-use. RefRegistry.validate (assets.py) checks device and frame metadata but not intervening input. ActionService.click validates age and mapping before actual input. A captures; B clicks under the same device lock; A subsequently clicks a still-fresh-by-age reference. Per-operation mutual exclusion does not prevent stale-state action. Define device mutation epoch/fresh guard for new controlled action references; acquire device owner before validation, advance epoch conservatively before any possibly effective action; prevent old references crossing intervening effects, even unknown outcome. For legacy primitive APIs preserve shape and explicitly specify compatibility behavior; distinguish raw coordinate operation from guarded input, do not promise exclusion against external ADB. Acceptance: deterministic A capture -> B effect -> A old ref rejected, fresh ref accepted, unrelated device epoch unchanged; crash after pending effect invalidates old guarded references.

F03 HIGH — Proof/interpreter seam. LifecycleService._proof (lifecycle.py:80) requires legacy binding and calls WorkflowRuntime._definition (runtime.py:100) with run device; legacy definition rejects a different source device. R04 proposes reuse, but MD-10 and MD-11 have no explicit common execution context / proof-verifier contract. Extract parameterized immutable definition resolution and target-bound interpreter/proof validation first, keeping legacy entrypoint semantics. Specify required profile, geometry, templates, source seal, target serial, receipt kind, proof fields, chronology and target-ref verification. Do not route portable runs through legacy registry guard or weaken old proof. Acceptance: old proof still passes with identical output, legacy B fails, portable B proof passes only using B observations; wrong binding/kind/device or substituted source frames fails.

F04 HIGH — Qualification CAS and drift. R04/R05 assign both pair-level and family-level state without defining their ownership. Define qualification slot key (portable_id, explicit serial), independent monotonically increasing generation and immutable qualification records, active/revoked/invalidated states, exact CAS semantics; family revision generation remains separate. Decide how identity changes/reconnect are represented; serial is the supported logical identity, not proof of physical identity. Profile/geometry drift invalidates the active qualification durably, including after profile returns to former values; unavailable transport is not automatically profile drift. Provide explicit requalification, no automatic resurrection. Admission pins revision + qualification generation/ID atomically. Acceptance: concurrent revoke/replace/admit, multi-family reuse, drift then restore, offline then reconnect, revision change.

F05 HIGH — Atomic child reservation and owner/reconciliation. R08 requires durable parent and deterministic child IDs but not durable reservation semantics or a concrete owner state transition. Define admission transaction reserves parent, every child task/run ID, pinned proof/generation before dispatch; define owner lifecycle for parent and children, same-request lookup before fresh admission checks, collision/conflict before effects. Do not infer child abandonment solely from parent death; verify actual child owner, especially if a subprocess survives. Keep live child receipt untouched and forbid resubmission; reconcile dead owners only. Acceptance: collision with independent task, crash between admission and launch, live duplicate, parent loss with surviving child, pending effect, terminal child, no duplicate click. Batch status truth table for all completed, mixed, none completed, interrupted and busy/rejected children.

F06 MEDIUM — Evidence validation consistency. validation_context._seal reads session/events/annotations/frame index/files; validate_cached uses before/after seals; Recorder.annotate can append annotations independently of workspace_lock, and source sessions are not necessarily immutable. R02/R07 need a stable source evidence read/publish boundary. Define a consistent read snapshot or immutable revision seal, verify again at commit; concurrent changes invalidate validation/publication with a structured error, never silently cache stale proof. Protected frame retention and immutable templates must remain intact. Acceptance: mutate annotation/source evidence during validation and publication; no publication based on inconsistent seal, no deadlock or false cache hit.

F07 MEDIUM — Contract freeze ownership. R09 explicitly requires schemas/error envelopes before implementation, whereas MD-14 finalizes them after MD-13. Add first contract/design ticket for exact API names, input/output examples and schemas, receipt state machines, kind-separated ID namespaces, atomic claim/lock ordering, qualification CAS and batch truth table. MD-14 becomes compatibility verification only. Acceptance: contract fixtures/schema tests covering accepted/rejected requests and default legacy behavior; every implementation ticket cites versioned contract.

## Additional decisions requiring explicit resolution
- Legacy registry activation race: current guard_run (lifecycle.py:238), orchestrator._pin/_child/_reconcile and recovery selector expect the old outer lock across a task. R05 defines pin semantics for portable tasks only. Choose and document legacy admission/activation behavior, including recovery children if family generation changes while a run is active. Preserve old externally observable behavior or version it explicitly, test interleaving. Do not just remove long lock.
- Device Discovery: R01 asks exact adb state parsing; current implementation is core/service/platform/adb/adb_platform.py:get_devices (151), while scope says no Core change. Permit narrowly scoped parser correctness fix with regression tests or implement a precise application-layer discovery adapter; no wider Core refactor. Distinguish discovery failure from empty successful list without breaking old response shape.
- Same-store execution only: lock is store+serial. Separate stores and serial aliases are outside guarantee; document and test scoped limitation. Physical identity attestation and cross-host locking are not Phase 9.
- Live qualification remains not attempted. Second authorized compatible device has not been established; do not conflate synthetic overlap with live E2E.
- Initial batch bounds 16 devices / max concurrency 4 are proposed product limits, not throughput benchmark.

## Recommended ticket restructuring
Retain one Orca project/worktree. Existing dependency graph is acyclic and covers IDs, not sufficient semantic completeness. Avoid concurrent writes on same checkout. Revised sequence (proposed, not applied):
C00 freeze contracts and test fixtures (none).
C01 explicit discovery (C00).
C02 frame/index metadata transactions (C00).
C03 immutable asset revision + reference pinning (C02).
C04 device/request owner coordinator (C02).
C05 device epoch/fresh guard (C01,C04).
C06 migrate bare CLI/MCP and Recorder (C03,C05).
C07 migrate Transition (C06).
C08 migrate legacy Runtime/Recovery (C07).
C09 registry/admission and consistent validation snapshot (C08); specify legacy activation/recovery semantics.
C10 contract old gate, prove multiprocess overlap (C09).
P01 extract common definition/interpreter/proof contract preserving legacy (C00,C08).
P02 publish portable revision (P01,C03,C09).
P03 portable preflight (P02,C10).
P04 portable trial (P03).
P05 qualification slot CAS and commit/revoke (P04).
P06 portable family revision and pinned single execute (P05).
B01 batch atomic admission/ID reservations (P06).
B02 bounded execution and parent/child reconciliation (B01,C10).
V01 compatibility and frozen store verification (B02).
V02 independent live two-device qualification (V01).
21 proposed tickets; split C09 further if proof-seal and registry migration cannot fit one context. Each ticket needs explicit external behavior acceptance, tests and implementation ownership. Use existing high-level seams and real process barriers, not mocked locks/proofs. Freeze acceptance contract before implementation; maintain green integration at expand/migrate/contract boundaries.

## Conclusion
Architecture approved in direction only. F01–F05 block dispatch; F06/F07 must also be resolved in revised planning. No source/production/store changes. Do not launch DAG until revised SPEC, tickets, and contract are consistent. Review does not claim implementation bugs in not-yet-written code or a fresh-agent review.
