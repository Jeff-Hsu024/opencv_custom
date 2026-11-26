# MD-04: Migrate primitive, Recorder and Transition entrypoints

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Route all bare and recorded device I/O via coordinator, retain compatibility outer gate until contract.

**Blocked by:** MD-01, MD-03

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC01,UC08,UC09,UC11,UC13; R01,R06,R07,R09; A01,A06,A08

## Acceptance criteria
- [ ] Snapshot/wait/click/swipe/type/key and transition CLI/MCP use same device exclusion; transition holds it through pre/find/action/wait/post.
- [ ] Preserve session/ref mismatch, semantic UNKNOWN, real failed-wait image and duplicate behavior.
- [ ] Pending click crash never replayed; no wrapper bypass; legacy tests green.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
