# C06: Primitive and Recorder migration

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Wire bare/recorded CLI/MCP device operations, scoped find and guarded click to coordinator and exact asset revision/epoch. Retain outer gate.

**Blocked by:** C03, C05

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC01,UC08,UC13,UC15,UC16; R01,R07,R10,R11,R14; A01,A06,A11,A12,A15; F01,F02,F05

## Acceptance criteria
- [ ] All possible legacy effects advance epoch; legacy unversioned shapes retained, stamped stale refs rejected; guarded click durable action ID.
- [ ] Recorder session event allocation/pin exact revision/digest and active status serialized; scoped find and click produce standard events.
- [ ] Two clients contend on same serial; no foreign frame/session/ref input, no duplicate guarded click.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
