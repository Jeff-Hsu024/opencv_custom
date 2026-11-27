# B02: Bounded parallel execution and reconciliation

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Run children with own owner/device lock and bounded pool, aggregate authoritative child outcomes and reconcile actual live vs dead owners.

**Blocked by:** B01

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC07,UC10,UC11,UC18; R07,R08,R14; A06,A07,A08,A15; F05

## Acceptance criteria
- [ ] Barrier proves overlap and per-batch bound; busy/drift/failure child isolated; exact aggregate truth table.
- [ ] Parent loss while child survives: live child untouched, admission closed, unstarted not_attempted; later reconcile dead only.
- [ ] Transport timeout inspect original IDs, terminal child preserved, pending effect unknown, no replay/re-dispatch or image fan-out.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
