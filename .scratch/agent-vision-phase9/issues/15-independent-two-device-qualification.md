# MD-15: Independent two-device E2E and raw audit

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Fresh agent uses candidate Skill/CLI/MCP and isolated store; reversible settings route on explicitly authorized A/B, then raw audit.

**Blocked by:** MD-14

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC01–UC14; R01–R09; A01–A10

## Acceptance criteria
- [ ] One source exploration; B qualifies with same portable ID/templates and zero new exploration; two repeated runs each plus actual overlapping batch.
- [ ] Negative tests for incompatible device, wrong ref, same-device contention, duplicate/conflict and partial batch; final reversible state verified.
- [ ] Raw SQLite/PNG/journals/JUnit audit and frozen main/tag/official deployment unchanged; if second authorized device absent, live gate NOT_ATTEMPTED/BLOCKED, never fixture-as-live.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
