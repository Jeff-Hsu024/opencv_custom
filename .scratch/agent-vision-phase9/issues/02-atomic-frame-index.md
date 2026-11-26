# MD-02: Shared Store metadata and protected frame transactions

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Introduce short metadata transaction seam for frame index publication, pinning, protection and retention; keep old outer operation gate.

**Blocked by:** None

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC13,UC14; R07,R09; A06,A09

## Acceptance criteria
- [ ] Real process barrier: concurrent save/protect/cleanup has no lost index entries, missing protected PNG or altered evidence hashes.
- [ ] Active refs/readers protected against TTL removal; crash orphan cleanup never removes protected evidence.
- [ ] Existing JSON/index shape and legacy hashes unchanged; no capture/poll/sleep under metadata lock.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
