# C00: Contract fixture freeze

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Contract only: exact schema, examples, receipt/lock/owner and storage state diagrams; validate and freeze contract test fixtures before any source changes.

**Blocked by:** None

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC01-UC21; R01-R16; A01-A17; F01-F07

## Acceptance criteria
- [ ] Validate all 29 request schemas against draft 2020-12 and all positive/negative examples; add response/semantic fixtures for state tables, CAS, locks and ID namespaces.
- [ ] Record contract hash and exact baseline public tool/default shapes; fixtures exercise both CLI/MCP contract, no production code changes.
- [ ] Resolve any inconsistency by explicit design amendment before downstream dispatch; no silent schema drift.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
