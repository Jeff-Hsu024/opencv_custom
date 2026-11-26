# P02: Shared target-bound deterministic interpreter

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Extract interpreter accepting sealed ResolvedDefinition, ExecutionContext, owner; legacy wrapper retains original lifecycle/binding contract. No duplicate runtime implementation.

**Blocked by:** P01

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC05,UC06,UC09,UC11; R06,R11,R12; A04,A08,A12,A13; F02,F03

## Acceptance criteria
- [ ] Legacy run results unchanged including recovery and failed evidence; source-bound legacy B still rejected.
- [ ] Injected valid context and fixture target demonstrates same matcher/guards, profile/geometry checks, pending intent, epoch and fresh refs.
- [ ] Reject mismatched context/kind/identity; portable context must not consult legacy active registry.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
