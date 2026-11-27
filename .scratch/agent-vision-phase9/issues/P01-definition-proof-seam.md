# P01: Immutable definition resolver and proof verifier

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Extract shared immutable definition resolution and proof verification using expected context; legacy wrapper retains source guard and identical output.

**Blocked by:** C11

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC02,UC03,UC05,UC14; R02,R12; A02,A13,A09; F03,F06

## Acceptance criteria
- [ ] Legacy source proof still exactly same output; legacy B rejected; substituted frames/refs/kind/binding/geometry/hash rejected.
- [ ] Target-bound verifier checks all actual step guards, receipts, chronology and fresh refs, new epoch evidence; no mocked proof success.
- [ ] No portable trial or family yet; legacy tests green.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
