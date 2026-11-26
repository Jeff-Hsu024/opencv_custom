# C05: Durable Device Action Epoch

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Implement frame/ref epoch sidecars and atomic epoch/intent primitive under device owner; no adapter cutover yet.

**Blocked by:** C01, C04

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC16,UC08,UC09; R11,R07; A12,A06; F02

## Acceptance criteria
- [ ] Stamped A ref after intervening A effect rejected even within TTL; fresh ref accepted; B epoch unchanged.
- [ ] Unknown/pending crash increments durable epoch; capture/derived refs inherit correct epoch, no rollback.
- [ ] Old refs retained; new guarded path rejects unstamped; legacy compatibility semantics and raw epoch advance defined in tests.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
