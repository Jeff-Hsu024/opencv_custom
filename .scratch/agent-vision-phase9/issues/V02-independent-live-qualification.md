# V02: Independent two-device qualification

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Fresh independent agent uses only candidate Skill/CLI/MCP and isolated store on explicit compatible reversible A/B; audit raw receipts.

**Blocked by:** V01

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC01-UC21; R01-R16; A01-A17; F01-F07

## Acceptance criteria
- [ ] Learn once on A; same portable ID/templates, B qualification with zero B learning; two repeated successful runs each and real batch overlap.
- [ ] Negative cases and protected evidence, exact final reversible screen; independent raw SQLite/PNG/journal/JUnit audit.
- [ ] If second authorized live device absent, live gate NOT_ATTEMPTED/BLOCKED; fixture never equals live. No merge/deploy.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
