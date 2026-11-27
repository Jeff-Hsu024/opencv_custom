# C08: Legacy Runtime and Recovery migration

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Move legacy run/qualify/recovery through same owner; preserve binding/source guard and existing recovery behavior; compatibility gate still active.

**Blocked by:** C07

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC08,UC09,UC11,UC14; R06,R07,R11,R14; A06,A08,A09,A12; F02,F05

## Acceptance criteria
- [ ] Legacy B rejected; old proof/qualified run and one allowed recovery retain behavior; no nested lock deadlock.
- [ ] Pending effect advances epoch and actual failed post-frame preserved; interrupted receipt only reconciles dead owner.
- [ ] Legacy JSON receipts and old names/defaults unchanged.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
