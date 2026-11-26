# MD-07: Contract: enable per-device concurrency

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Remove obsolete long-held global gate only after all cooperating entrypoints migrated; metadata still serialized briefly.

**Blocked by:** MD-06

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC07,UC08,UC11,UC13,UC14; R07,R09; A06,A08,A09

## Acceptance criteria
- [ ] Real subprocess barrier proves A/B simultaneous device I/O in same store; same device raw CLI versus recorded MCP has one owner.
- [ ] Concurrent frame/session/registry stress and process termination pass, no deadlocks or lost evidence.
- [ ] Document one-store/upgraded-process boundary and quiescent cutover; baseline regression green.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
