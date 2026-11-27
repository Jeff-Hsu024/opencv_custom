# P07: Portable family revision registry

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Family publish/activate/disable/inspect/list with separate generation, immutable revision->portable ID and source seal checks.

**Blocked by:** P06

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC12,UC17,UC14; R05,R13,R15; A05,A14,A16; F04,F06

## Acceptance criteria
- [ ] New family generation0 and inactive; publish/activate CAS and revision monotonic; stale generation rejects.
- [ ] Qualification slots independent of family; same portable definition reused across families, no copied qualification on new revision.
- [ ] Legacy family namespace untouched; source changed invalidates new admission, no history rewrite.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
