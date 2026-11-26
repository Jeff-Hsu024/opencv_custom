# Phase 9 — Use cases: Learn Once, Qualify Per Device, Execute Many
Status: proposed planning baseline, 2026-11-26. No implementation or live device actions.
Base: bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb (agent-vision-v0.2.0).

## Goal
An LLM explores a supported Android task once on device A, turns the evidence into one reusable, immutable portable workflow, explicitly qualifies that same workflow on B and other compatible devices, and executes it repeatedly without rediscovering the task. Each execution has independent device-scoped evidence and durable outcomes; parallel device work must not corrupt the shared store or repeat uncertain actions.

## Actors / terms
Agent (explores, selects serial, interprets semantic evidence); operator (chooses device allowlist and authorizes live trial); workflow publisher (promotes proven learning); runtime (deterministic execution); orchestrator (dispatches qualified tasks); auditor (inspects journals). Source device is immutable provenance, not a target default. Qualification is device + workflow revision + observed profile + geometry specific. Read-only preflight is NOT successful live qualification. A device permit in this document is explicit selection for the task, not a new authentication system.

## Scenario catalog
Each scenario includes entry conditions, behavior and observable outcome. A and B denote distinct authorized ADB serials, not hardcoded emulator indexes. C may be absent or incompatible. All examples use an isolated, reversible settings-navigation flow; no account, purchase, resource, persistent settings change.

| ID | Actor / scenario | Preconditions and main path | Expected observable result / negative path |
|---|---|---|---|
| UC01 | Agent discovers/selects devices | A and B connected; list via CLI/MCP; explicitly choose A/B | Both online serials visible; desktop separate; offline/unauthorized not actionable; no auto-select or connect/start. Unknown/ambiguous ID rejected before input. |
| UC02 | Agent learns once | On A, record snapshots, fresh targets, clicks, postcondition observations and semantic PASS; compile and prove complete existing workflow | Existing v1 bundle/source journal unchanged; completed proof on A available; no new learning on B. Failed or incomplete source proof cannot publish. |
| UC03 | Publisher creates reusable template | Select proven A workflow/run; publish immutable portable revision with exact profile and geometry requirements and sealed source | Portable identity independent of target serial; same inputs produce same identity; source device still in provenance. Tampered evidence/template or incompatible source proof rejected. |
| UC04 | Agent checks B without actions | Select portable revision and B; probe actual package/version/rotation/locale/UI mode, geometry, initial state and first unique target | Preflight receipt B, no click; mismatch/ambiguous/missing target => precise reason + actual observation; no batch eligibility. |
| UC05 | Operator authorizes trial on B | Successful B preflight; explicitly run bounded trial with fresh run ID | Complete all state/target/receipt guards and obtain semantic acceptance on reversible workflow; qualify B using completed verified proof. Failure/unknown effect leaves B unqualified, no replay. |
| UC06 | Agent runs qualified A or B | Active portable revision, exact device qualification, unique caller task ID; select device and execute | Same portable revision, separate bindings and evidence; all targets freshly detected; actual final state verified. No re-exploration; duplicate returns same receipt. |
| UC07 | Agent executes on many | Explicit distinct qualified A and B, bounded concurrency 2; submit batch with deterministic child IDs | Both execute overlapping live intervals, each own result/frame/device; batch aggregates success/partial/needs_agent. No lock held across unrelated waits. |
| UC08 | Agents compete for same device | Two processes/clients submit tasks or recorded actions on A; B independent | At most one cooperating controller on A; competing request busy before action or returns same durable request; B progresses. No stale ref from A used on B, including across sessions. |
| UC09 | Device drift/disconnection | B changes app version, rotation, locale, UI mode, geometry, serial unavailable, or unexpected state | Fail closed; distinguish not_attempted vs uncertain post-action. Fresh evidence retained if available. No action on incompatible B; other device unaffected. Requalification explicit after drift. |
| UC10 | Batch with failure | A succeeds; B fails after a click or C lacks qualification | Admission rejects whole request before action for invalid/duplicate/unqualified target list; after admission a runtime failure affects that child only. Partial result, no blind retry, no cross-device recovery. |
| UC11 | Agent resumes after timeout/crash | Transport response lost, worker exits or parent dies during batch/transition/run | Inspect original IDs, distinguish live owner from abandoned receipt, reconcile without replay. Crash releases OS-backed lock; abandoned pending action remains unknown. Completed child stays completed. |
| UC12 | Publisher evolves workflow | Publish revision 2; promote with expected generation; device proofs exist only for revision 1 | New revision requires qualification on each device; existing admitted run pinned to revision 1; no new admissions under stale generation; old receipts inspectable. |
| UC13 | Auditor verifies shared store | Parallel A/B capture, protection, cleanup, session annotations, registry operations; restart processes | No lost index rows, missing protected PNG, foreign device references or duplicate events; SQLite integrity and immutable evidence hashes pass. CLI/MCP same contract; native image remains usable. |
| UC14 | Maintainer upgrades legacy deployment | Copy official 0.2.0 store into isolated candidate; run existing legacy CLI/MCP tools and workflows | Legacy source-device behavior and existing IDs/proofs unchanged, old calls and result shapes supported, no implicit portability; rollback by separate consistent backup. No production mutation during development. |

## Business success measures
- One source learning/compile/publish; B qualification uses identical portable revision/templates and zero new Recorder exploration sessions.
- A and B each complete at least two repeated runs after qualification; different fresh refs, correct serial, complete step evidence; no unexpected device input.
- Actual overlap of device execution intervals under one shared Store; deterministic barrier fixture proves concurrency (not inferred from wall time). Compare serial and parallel duration for same controlled route, report rather than promise speedup.
- Same-device contention, request-ID conflict, profile drift, transport/crash, protected failure evidence, concurrent index writes and registry CAS verified by negative tests.
- Actual two-device E2E remains NOT_ATTEMPTED until a second explicitly available/authorized device is supplied. Synthetic two-device tests do not substitute.
- Original 308 regression cases remain green plus new acceptance coverage. No UI manipulation of unrelated devices.

## Boundaries / decisions for review
First release: exact profile + geometry compatibility only; no scaling/cross-version adaptation, fuzzy semantic automation, automatic discovery of new targets, cross-host distributed scheduler, uncontrolled external ADB arbitration, multi-device recovery-route learning or hidden retries. One Worker host / ADB server / shared store; different serials can be different devices but aliases of the same physical device are not supported concurrently. Keep legacy v1 execution/recovery; portable v2 failure hands off explicitly. Qualification trial is a real run, separately authorized, not read-only preflight. Explicit device selection and portable enrollment prevent implicit broadcast.
