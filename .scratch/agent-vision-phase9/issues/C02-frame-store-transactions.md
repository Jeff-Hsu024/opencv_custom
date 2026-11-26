# C02: Frame index transactions and active pins

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Short cross-process metadata transaction, atomic ID reservation, frame PNG/index publication, pin lifetime and retention; preserve JSON index and outer gate.

**Blocked by:** C00

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC13,UC14; R07,R15; A06,A09,A16; F06

## Acceptance criteria
- [ ] Multiprocess save/protect/cleanup barrier: no lost rows, missing protected PNG or ID overwrite.
- [ ] Crash before/after PNG/index commit and cleanup: orphan only, no dangling protected refs; pins survive active owners and reconcile dead owners.
- [ ] No capture or OpenCV matching under metadata lock; legacy index/evidence hashes compatible.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
