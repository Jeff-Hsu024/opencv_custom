# Phase 9 - Targeted Final Acceptance Requalification

Date: 2026-11-27 (Asia/Taipei)
Role: Independent Acceptance Auditor
Scope: FA-01 remediation, final regression provenance and candidate package; no new full audit or live campaign.

## Finding dispositions

| Finding | Original severity | Disposition |
|---|---|---|
| FA-01 | HIGH / blocking | CLOSED - independently verified in Runtime and Portable Preflight; original mixed-fault tests and new regression pass. |
| FA-02 | LOW / non-blocking | CLOSED - consolidated final-code provenance verified against all 27 individual receipts and JUnit results. |
| FA-03 | INFORMATIONAL | RETAINED / non-blocking - explicit qualification scope limitation, not a product defect. |

## Candidate identity and diff

- Rejected candidate: 770e1de7c53c71de957c69f41291e3b089b0a5c4.
- Corrected tested code: fc1d2050a4e2f91fe0720a02be22d88a834dd900.
- Actual worktree HEAD before and after targeted execution: 6b9d8ad604730bc076630b9305cf65ccce41d992.
- git diff 770e1de fc1d205 changes exactly vision_app/runtime.py, vision_app/portable_service.py and vision_app/test/test_capture_guard_precedence.py. Production change is 9 inserted lines and 3 removed lines; new test file 151 lines.
- git diff fc1d205 6b9d8ad changes only IMPLEMENTATION_STATUS.md, final-acceptance/RESOLUTION-FA01.md and final-acceptance/regression-summary-fa01.json. No production or test delta. Tracked worktree clean before report creation; pre-existing untracked artifacts left intact.

## FA-01 independent production-code review

Read original FINDINGS.md, RESOLUTION-FA01.md, regression-summary-fa01.json and both original auditor-owned tests. Reviewed full production diff and surrounding control flow rather than accepting the resolution narrative.

- WorkflowRuntime._capture: first profile check unchanged; snapshot protected and actual frame journaled before validation. Device identity, width/height and portable rotation guard now precede the second profile check. A confirmed mismatch raises GEOMETRY_MISMATCH with frame evidence and never enters the transient PROFILE_UNKNOWN retry branch. Valid frames still undergo the second profile equality check and portable shape validation.
- PortableService.preflight: retains initial profile probe/shape/equality, protected capture, frame ID and epoch. Captured device/geometry comparison (including rotation, with existing absent-rotation fallback) now precedes latest-profile probe; confirmed drift includes frame ID in fault details. Valid captures still require second shape/equality, unique initial state and target plus metadata recheck. Failure receipt and existing slot invalidation path retained; no input/epoch advance.
- _interpret is unchanged: only exact transient focused/resumed PROFILE_UNKNOWN is retried, inside existing deadline, remaining sleep and MAX_CAPTURES; mismatch is propagated. Postcondition verification retains deadline check after classification. Pre-action guard, reference epoch/age check, durable ActionIntent, action pending/unknown handling and receipt persistence unchanged. No replay or input retry introduced.
- PortableService.live_guard and QualificationSlots.invalidate unchanged: only confirmed PROFILE_MISMATCH or GEOMETRY_MISMATCH invalidates; CAS is scoped to portable ID/device and compares observed generation, qualification ID and active status under transaction; increments once. Unknown probe does not invalidate. Admission duplicate handling unchanged. New tests explicitly assert B invalidated generation 2, unchanged A slot, protected frame, executed_unverified, exact duplicate, one action and correct epoch; preflight remains zero-input.
- No new contract violation or weakening identified in changed paths. Prior unknown-rotation and legacy semantics are preserved, not expanded by this correction.

## Targeted independent execution

Command from existing worktree (PYTHONPATH=core;.;vision_app/test, unique VISION_STORE_DIR, PYTHONDONTWRITEBYTECODE=1):
```
.scratch/c00-env/Scripts/python.exe -m pytest specs/agent-vision-phase9/final-acceptance/test_focus_geometry_audit.py specs/agent-vision-phase9/final-acceptance/test_recheck_mixed_fault.py vision_app/test/test_capture_guard_precedence.py -q -p no:cacheprovider --junitxml=<new-scratch>/targeted.xml
```

| File | Cases | Result |
|---|---:|---|
| test_focus_geometry_audit.py | 1 | passed |
| test_recheck_mixed_fault.py | 2 | passed |
| vision_app/test/test_capture_guard_precedence.py | 10 | passed |
| Total | 13 | 13 passed, exit 0, 62.88 s; zero failure/error/skip |

Original auditor files SHA-256 identical before and after:
- test_focus_geometry_audit.py: 71d73cc67c2b25c811d077e65f02f72d7139f688f0b30f051d8fcbf6b822457e
- test_recheck_mixed_fault.py: 298cc844e2e1e0c974e8f83c7a0b678f2f36f7833d8bdc707aaaaa171b1c11a8

These are untracked original auditor assets; no pre-existing source hash attestation is claimed. They were run directly, not copied, rewritten or replaced. Historical exit receipts show the original rejected commit and failing invocations. New evidence: .scratch/agent-vision-phase9/verification/independent-requalification-20261127/retry/targeted.{xml,log,receipt.json}. Initial invocation used the connector's default 30 s timeout and ended without a result receipt; it is not counted. Retry used 120 s and a fresh isolated Store; verified actual process exit and parsed JUnit. No historical evidence overwritten.

## FA-02 consolidated regression verification

Independently parsed each original *.result.json, *.args, *.xml and *.log in .scratch/agent-vision-phase9/verification/fa01-resolution, comparing to tracked summary; did not rerun the consolidated suite. For each shard verified commit, zero exit, command and XML/args path, distinct isolated Store, exact JUnit SHA-256, suite counts, actual testcase elements and identities matching argument list, no failure/error/skip nodes and matching passed count in log.

| Shard | Cases |
|---|---:|
| agent_interface-1 | 8 |
| agent_interface-2 | 8 |
| app-1 | 38 |
| app-2 | 38 |
| app-3 | 37 |
| app-4 | 37 |
| app-5 | 38 |
| capture-guard | 10 |
| contract | 978 |
| core | 132 |
| failure_evidence-1 | 9 |
| failure_evidence-2 | 9 |
| failure_evidence-3 | 9 |
| lifecycle-1 | 7 |
| lifecycle-2 | 6 |
| orchestrator-1 | 6 |
| orchestrator-2 | 5 |
| orchestrator-3 | 5 |
| orchestrator-4 | 5 |
| recovery-1 | 6 |
| recovery-2 | 5 |
| recovery-3 | 5 |
| runtime-1 | 6 |
| runtime-2 | 6 |
| runtime-3 | 9 |
| workflow-1 | 11 |
| workflow-2 | 11 |
| Total | 1444 |

27/27 receipts, 27/27 XML hashes and 27/27 testcase identity sets match. All 1,444 distinct cases at fc1d205: 466 regression and 978 frozen contract, no failure/error/skip. Union exactly matches retained collection; independent fresh --collect-only on current code yields same 1,444 identities. Historical baseline mapping 308/308 covered (one formerly unparameterized transition case maps to [False]). Fresh independent frozen hash checks 26/26, exact legacy MCP definitions 61/61, additive input schemas 29/29. Historical 1,429/1,004/21 totals are not added; independent targeted 13 cases are separately reported, not added to consolidated count. Receipts are local evidence, not cryptographic attestation of execution time or external infrastructure.

## Rebuilt candidate wheel

Artifact: .scratch/agent-vision-phase9/verification/fa01-resolution/wheels/opencv_custom-0.2.0-py3-none-any.whl
Size 176981 bytes; independently recomputed SHA-256:
1fe7c1334dd4f8e5a0e6beeb9e612cf372504a7b07ac49624a027683b043f8cc.

ZIP integrity good. All 59 shipped Python files match fc1d205 Git blobs after LF normalization and match retained isolated installed files byte-for-byte. Both changed production modules included. All 63 hashed RECORD entries independently verified (64 archive entries including RECORD itself). Extracted wheel into new scratch wheel-target; independently imported Runtime and PortableService from that target, invoked actual CLI portable-list and MCP vision_portable_list against a new isolated Store, exact empty result parity and 90 tools confirmed. No production install. This verifies the rebuilt artifact, not a new independent build.

## V02 retained live evidence and sufficiency

Reviewed prior independent REPORT.md and direct live campaign report against V01/V02 acceptance criteria and the correction's impact. Original independent raw checks (33/33) and positive direct Apps and fresh independent Sound Settings campaigns at predecessor 770e1de remain valid historical evidence. They used two explicitly selected compatible Android devices, same profile per campaign (Settings 720x1280, rotation 0), A-only learning, B qualification with no B learning, same immutable portable definition/templates within each campaign, repeated successful runs and actual overlapping batch effects, negative/idempotency cases, protected PNG/SQLite/journal evidence and exact reversible final screens. Separate fresh Store and independent agent/definition retained.

The correction only changes precedence when actual captured geometry/identity is already invalid. Valid-geometry paths still require both profile probes, classification, action intent, deadline and CAS; new valid-geometry transient-focus controls pass. No change to device transport, image capture, coordinate transforms, action dispatch, learning, qualification proof, batch scheduling, CLI/MCP routing or packaged source outside these guards. Existing positive evidence therefore remains sufficient for the agreed same-profile platform qualification when combined with corrected-code regression, independent targeted tests and wheel provenance/smoke. No indispensable new Android evidence gap identified. Do not relabel prior live campaigns as fc1d205 executions; no new Android operation was performed.

FA-03 remains informational: no CZN automation, heterogeneous profile portability, cross-host execution, external controller or physical-device identity attestation, or deployment readiness established. Prior independent correlation was not an exhaustive second implementation of multi-match. These boundaries remain explicit.

## Closure and boundaries

V01: MAY CLOSE. Prior frozen Store/rollback, compatibility and ImageContent evidence retained; final-code regression provenance gap now independently closed.
V02: MAY CLOSE. Existing independent positive live evidence plus verified targeted correction satisfies the stated scope. No additional live campaign required.

Only this report and new isolated scratch artifacts written. No production code, original test/evidence files, official Store, main or release tags changed; no DAG, worker dispatch, merge, push, deployment or ticket state mutation.

Final decision: PASS_WITH_NON_BLOCKING_FINDINGS
