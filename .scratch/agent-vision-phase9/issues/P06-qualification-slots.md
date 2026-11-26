# P06: Per-device Qualification Slot CAS

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Implement commit/revoke/inspect/list/record, independent generation and immutable qualification history, durable confirmed drift invalidation; wire preflight/trial drift seam.

**Blocked by:** P05

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC05,UC09,UC12,UC17; R04,R13,R14; A04,A05,A14,A15; F04,F05

## Acceptance criteria
- [ ] Valid B complete trial + semantic PASS; source A first enrollment only; wrong proof/device/revision/non-PASS fails.
- [ ] CAS revoke/replace/admit race; exact duplicate returns historical receipt not reactivation; drift then restore stays inactive; offline reconnect alone does not invalidate.
- [ ] New post-invalidation trial required; separate generation across family reuse; old proof immutable.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
