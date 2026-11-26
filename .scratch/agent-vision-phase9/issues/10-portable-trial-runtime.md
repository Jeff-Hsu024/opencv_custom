# MD-10: Explicit qualification trial on target device

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** Trial uses explicit serial and preflight, shared deterministic interpreter with portable definition rather than legacy source binding.

**Blocked by:** MD-09

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC05,UC09,UC11; R04,R06,R07,R09; A04,A08

## Acceptance criteria
- [ ] Same immutable templates execute on B with fresh B refs, revalidate before each action, persist pending effect and verified postconditions.
- [ ] Failed/unknown trial retains actual evidence; duplicate and conflicting run IDs never replay.
- [ ] Completed trial alone is not enrollment; legacy source-device guard intact.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
