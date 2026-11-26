# MD-06: Migrate registry and legacy task admission

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Migrate lifecycle CAS, selector, builder, validation and task admission to short metadata operations and shared owner context; keep compatibility gate.

**Blocked by:** MD-05

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC08,UC11,UC12,UC13,UC14; R05,R06,R07,R09; A05,A06,A08,A09

## Acceptance criteria
- [ ] Concurrent registry CAS linearizes; proof and immutable evidence remain checked.
- [ ] Legacy task pins family/version/device/profile; child receipts/ID claims atomic; uncertain action not restarted.
- [ ] No device waits under metadata lock; nested calls reuse owner; legacy response unchanged.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
