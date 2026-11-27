# C07: Recorded Transition migration

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Use same owner across pre/find/click/wait/post; scoped_transition uses exact revisions and epoch, legacy transition retains receipt contract.

**Blocked by:** C06

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC08,UC09,UC11,UC15,UC16; R07,R10,R11,R14; A06,A08,A11,A12,A15; F01,F02,F05

## Acceptance criteria
- [ ] Both transition forms preserve actual failure frame, event sequence and semantic UNKNOWN; no stale/cross-scope ref.
- [ ] Persist pending/epoch before click; kill after pending, duplicate original receipt, no replay.
- [ ] Existing Builder can compile supported scoped click events; old transition shape and tests green.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
