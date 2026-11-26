# MD-14: Compatibility and agent-facing release contract

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Finalize actual CLI/MCP schemas and Skill; verify copied 0.2.0 store and candidate packaging/migration/rollback instructions.

**Blocked by:** MD-13

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC01–UC14; R01–R09; A09

## Acceptance criteria
- [ ] 61 prior tool names/default shapes and 308 prior distinct tests remain green, new schemas documented.
- [ ] Legacy IDs/proofs/families/protected hashes unchanged in copied store; official store untouched.
- [ ] Native image and metadata-only parity; document shared-store limit, explicit trial, drift, timeout inspection and no portable recovery.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
