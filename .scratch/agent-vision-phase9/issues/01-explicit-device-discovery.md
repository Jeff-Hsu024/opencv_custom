# MD-01: Explicit Android discovery and target validation

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Use existing CLI/MCP discovery and explicit online serial selection; no auto-connect or start.

**Blocked by:** None

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC01,UC08,UC09; R01,R09; A01

## Acceptance criteria
- [ ] Two online serials plus offline/unauthorized fixtures: exact ADB state token, only online serials actionable; desktop remains separate.
- [ ] Invalid/unavailable serial rejected before input; no implicit adb/desktop alias on portable paths.
- [ ] CLI/MCP same discovery shape and target routing; no cross-device action.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
