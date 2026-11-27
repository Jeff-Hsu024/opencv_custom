# B01: Atomic parent admission and child reservations

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Durably reserve every task/run ID and pin all device qualification contexts in one transaction, no dispatch yet.

**Blocked by:** P08

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC07,UC10,UC11,UC18; R08,R13,R14; A07,A14,A15; F04,F05

## Acceptance criteria
- [ ] Explicit 1..16 distinct devices, concurrency 1..4 default2; invalid/unqualified/unknown list rejects entire admission with no child effects.
- [ ] Deterministic child IDs and collisions before admission; standalone cannot steal child; same request lookup before fresh checks.
- [ ] Crash before launch leaves reserved children; close admission makes unclaimed not_attempted; no partial reservation.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
