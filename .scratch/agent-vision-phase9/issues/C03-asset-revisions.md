# C03: Immutable scoped asset revisions

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Deliver scoped register/resolve and legacy alias compatibility with immutable PNG and coherent pointer; pin exact revision and retained digest.

**Blocked by:** C02

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC15,UC13,UC14; R10,R15; A11,A16,A09; F01,F06

## Acceptance criteria
- [ ] A/B same label, different immutable revision, exact scope/PNG metadata; wrong session/device fails.
- [ ] Interrupt between bytes and pointer/projection publication: old coherent alias or complete new revision; no torn PNG/JSON.
- [ ] Legacy named API retains shape and last-committed alias, original evidence untouched; Recorder pin seam available.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
