# P05: Explicit target-device trial

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Trial uses preflight+prun ID and target-bound shared interpreter, reserve owner before input, no enrollment.

**Blocked by:** P04

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC05,UC09,UC11; R04,R06,R11,R12,R14; A04,A08,A13,A15; F02,F03,F05

## Acceptance criteria
- [ ] Same immutable templates on B, all fresh B refs, proof verified against B context; no A frame/ref or new B learning.
- [ ] Fresh live rechecks, pending intent and actual failure frame; duplicate/conflict/dead owner never replay.
- [ ] Complete trial is not semantic PASS enrollment.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
