# MD-11: Commit and revoke device qualifications

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Commit completed matching proof + explicit semantic PASS to immutable qualification; source A enrollment may use original exact matching proof. List/inspect/revoke.

**Blocked by:** MD-10

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC05,UC09,UC12; R04,R05,R09; A04,A05

## Acceptance criteria
- [ ] Reject wrong device/revision, tampered/partial proof, non-PASS and unknown outcome.
- [ ] Stable qualification ID; explicit CAS replacement/revocation; audit old immutable proof.
- [ ] Different serial/revision not enrolled; drift requires explicit requalification.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
