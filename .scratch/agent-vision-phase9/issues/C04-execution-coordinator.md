# C04: Device and request owner coordinator

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** OS-backed cross-process owner/device locks plus thread mutual exclusion, atomic claim primitives, owner inspection; retain compatibility outer gate.

**Blocked by:** C02

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC08,UC11,UC18; R07,R14; A06,A08,A15; F05

## Acceptance criteria
- [ ] Canonical store+serial key and hashed IDs; bounded same-device contention; process kill releases lock; no inode replacement.
- [ ] Exact duplicate before current validation; conflict and reserved child rejected; live owner not reconciled.
- [ ] Lock ordering fixtures: parent/child/device/metadata, nested owner reuse, no metadata-to-device wait.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
