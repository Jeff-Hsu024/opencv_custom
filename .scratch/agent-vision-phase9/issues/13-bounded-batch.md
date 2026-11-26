# MD-13: Bounded parallel batch and durable child receipts

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Explicit ordered device list with parent admission and deterministic children, same single-device runtime; batch inspect/list and partial results.

**Blocked by:** MD-12

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC07,UC10,UC11,UC13; R07,R08,R09; A06,A07,A08

## Acceptance criteria
- [ ] 1..16 distinct serials, max_concurrency 1..4 default 2; invalid/duplicate/unqualified list fails atomically before input.
- [ ] Barrier proves overlapping child I/O and bound; B failure/busy/drift does not stop A; no cross-device recovery.
- [ ] Crash/transport loss preserves completed children, unstarted not_attempted and pending unknown; original ID inspection, no retry or image fan-out.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
