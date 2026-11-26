# P04: Read-only portable preflight

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Explicit serial, actual profile/geometry and first state/target guards; persist receipt and actual frame, no input. Introduce slot observation/invalidation seam if slot exists; enrollment implemented P06.

**Blocked by:** P03

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC04,UC09,UC17,UC21; R03,R13,R16; A03,A14,A17; F04,F07

## Acceptance criteria
- [ ] Exact B passes, mismatch matrix fails with precise reason and B frame/null; no B exploration or action.
- [ ] Successful preflight distinct from trial/enrollment; repeated live checks never trust old ref.
- [ ] Strict discovery failure vs empty; confirmed drift observation usable by P06, unknown/unavailable not drift.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
