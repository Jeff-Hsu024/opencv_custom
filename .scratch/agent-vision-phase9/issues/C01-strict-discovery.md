# C01: Strict Android discovery

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Exact online ADB state token and strict discovery API, retaining legacy discovery shape and desktop.

**Blocked by:** C00

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC01,UC09,UC21; R01,R16; A01,A17; F07

## Acceptance criteria
- [ ] Multiple online, unauthorized/offline/malformed/command failure fixtures; strict empty success differs from failure.
- [ ] Explicit serial only on new paths; no connect/start or fallback; legacy names/default output unchanged.
- [ ] Narrow Core parser fix only if needed; test actual adapter via existing seam.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
