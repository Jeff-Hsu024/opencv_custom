# P03: Publish proven portable definition

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** CLI/MCP publish/inspect/list from verified source run and complete dependency seal; one immutable content-addressed definition.

**Blocked by:** P02

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC02,UC03,UC19; R02,R12,R15; A02,A13,A16; F03,F06

## Acceptance criteria
- [ ] Same inputs same ID; source serial only provenance; exact profile/geometry and templates sealed.
- [ ] Incomplete/tampered/source changed before commit rejected; no mutable alias in portable template.
- [ ] Legacy workflow and source bytes unchanged; no device input.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
