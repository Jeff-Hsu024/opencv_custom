# P08: Pinned single-device portable execution

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Atomic task/run reservation and admission pinning family/slot/proof, execute target-bound runtime and inspect/list.

**Blocked by:** P07

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC06,UC09,UC11,UC12,UC17; R05,R06,R11,R12,R13,R14; A05,A08,A12,A13,A14,A15; F02,F03,F04,F05

## Acceptance criteria
- [ ] A/B same revision, separate qualified slots and fresh evidence; missing/inactive/stale/foreign rejection before input.
- [ ] Admit vs revoke/activate race linearizes; admitted context immutable, live drift stops and invalidates exact slot.
- [ ] Duplicate/conflict, task/run owner crash and pending effect no replay; no auto-recovery.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
