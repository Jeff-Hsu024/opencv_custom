# MD-05: Migrate legacy Runtime and Recovery

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Route qualify/run/recovery through one device owner, reuse internal locked calls, keep old source-device guard and compatibility gate.

**Blocked by:** MD-04

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC08,UC09,UC11,UC14; R06,R07,R09; A06,A08,A09

## Acceptance criteria
- [ ] Legacy source-device mismatch before action; old qualified run and single allowed recovery still work.
- [ ] Crash after pending effect reconciles to unknown/interrupted, not replay; actual failure evidence retained.
- [ ] Nested runtime/recovery no deadlock, existing behavior and result shapes unchanged.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
