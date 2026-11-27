# C09: Evidence snapshot and publication seal

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Consistent source dependency snapshots/pins/revisions for Recorder annotations, Builder, validation cache and retained evidence; validate outside metadata and CAS at publication.

**Blocked by:** C08

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC03,UC13,UC19; R02,R07,R15; A02,A06,A16; F06

## Acceptance criteria
- [ ] Concurrent annotation/dispute or changed dependency at validation/commit rejects EVIDENCE_CHANGED; no stale cache hit.
- [ ] Protected source/refs/template hashes retained, immutable snapshot pinned, later changes invalidate new admission without rewriting history.
- [ ] No long hashing/matching under metadata lock; existing offline validation unchanged for stable evidence.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
