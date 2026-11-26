# MD-03: Expand cross-process execution coordinator

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Add OS-backed per-device/request ownership and atomic ID claims under the compatibility outer gate. No bypass during expand.

**Blocked by:** MD-02

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC08,UC11,UC13; R06,R07; A06,A08

## Acceptance criteria
- [ ] Canonical store + serial lock key; no path traversal; bounded same-device busy; process death releases lock.
- [ ] Identical request returns in-progress/existing result; changed payload conflict; inspect live owner without marking interrupted.
- [ ] Document lock ordering and owner reuse; no recursive acquisition or metadata-to-device wait.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
