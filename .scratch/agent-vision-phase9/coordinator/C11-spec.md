# C11: Contract old gate and verify device overlap

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Remove only obsolete outer gate after auditing all upgraded input, metadata, registry, capture and offline paths.

**Blocked by:** C10

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC07,UC08,UC13,UC14,UC20; R07,R16; A06,A09,A17; F02,F05,F06,F07

## Acceptance criteria
- [ ] Real subprocess barriers prove A/B simultaneous device I/O, same-device raw vs recorded vs runtime one owner.
- [ ] Stress shared index, assets, sessions, CAS and process death; no deadlocks, lost evidence, extra input.
- [ ] Legacy regressions green; document one Store/cooperating process limit and quiescent upgrade.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.


Coordinator global constraints (normative task execution boundaries):
Read AGENTS.md, all nine specs/agent-vision-phase9 planning files, C00 REPORT.md, STATES.md, FREEZE.json and K08 amendment; implement this original ticket only against frozen contract. Existing project opencv_custom, feature branch feat/agent-vision-multi-device, current existing worktree only. No new projects/worktrees, main merge/push, release/deployment, official Store/archive or immutable acceptance evidence changes, no Queqiao wrapper. Do not edit coordinator-owned IMPLEMENTATION_STATUS.md or registration evidence. Serialize all writes under coordinator dispatch; do not launch workers or downstream tasks.
Preserve legacy 308 regression cases, 61 MCP tools/defaults, binding/proof/recorder/API, source-device guard; expand/migrate/contract with outer gate until C11. Agent-specific state in vision_app, preserve Core except narrowly allowed discovery fix. CLI/MCP share service and store; native MCP ImageContent. Shared metadata transactions, durable pre-input epoch, immutable revisions, independent family/slot CAS, atomic parent/child IDs, actual OS plus thread owner locks, no unknown replay, surviving live child never falsely interrupted. No mocking proof or ownership to manufacture success.
Use isolated temporary candidate stores and .scratch/c00-env Python as appropriate; never modify real evidence/bundles/device instances in tests. Run real targeted tests and required python -m pytest core/test vision_app/test -q with PYTHONPATH=core;. on Windows; report actual commands/exits/counts. Each implementation task commits scoped changes only on feature branch and writes its own concrete report/evidence paths; exclude coordinator files and unrelated changes. worker_done only with actual results, commit and evidence; failures must be reported honestly, never marked success. Contradictions require precise evidence and coordinator escalation, no silent contract/hash changes or blind retries.
No device input until two explicitly selected authorized compatible Android devices are established. Currently only 127.0.0.1:16480 and desktop externally observed; desktop is not Android. Never start/connect/operate other devices. V01 is independent compatibility verification with real subprocess barriers and consistency/crash/revocation/drift/timeout/duplicate/batch tests. V02 must be a fresh independent agent: raw SQLite/PNG/journal audit, A learns once, B same definition qualifies without re-exploration, two repeats each and actual overlap/isolation; if only one device remains report BLOCKED_LIVE_DEVICE, never fake PASS. Continue software-only acceptance where possible.
Placement: this machine (local), NB explicitly named by user.
