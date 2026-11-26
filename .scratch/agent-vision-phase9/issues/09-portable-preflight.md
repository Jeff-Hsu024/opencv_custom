# MD-09: Read-only preflight on compatible device B

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Select portable revision + explicit B serial; capture actual profile/geometry/state/first target; save observation and preflight receipt via CLI/MCP.

**Blocked by:** MD-07, MD-08

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC04,UC09; R03,R07,R09; A03

## Acceptance criteria
- [ ] Compatible B passes with zero clicks and zero new learning; preflight not enrollment.
- [ ] Mismatch matrix for profile/geometry/state/target none or ambiguous/disconnection; precise reason before input.
- [ ] Actual B failure frame or null when none; never substitute A frame; inspect receipt.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
