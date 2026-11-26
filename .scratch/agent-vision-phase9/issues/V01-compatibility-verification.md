# V01: Compatibility and frozen store verification

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Run baseline and new regression/contract suites; document actual Skill/CLI/MCP; verify copied v0.2.0 Store and candidate package, no deployment.

**Blocked by:** B02

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC01-UC21; R01-R16; A01-A17; F01-F07

## Acceptance criteria
- [ ] 61 existing tool names/default shapes and 308 baseline distinct tests pass; new schema/receipt/negative fixtures pass; actual counts reported.
- [ ] Copied old store legacy IDs/proofs/protected hashes intact; SQLite/PNG audit and rollback backup procedure; no frozen source/store changes.
- [ ] Native ImageContent and metadata-only parity, honest limits and timeout inspect behavior documented.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
