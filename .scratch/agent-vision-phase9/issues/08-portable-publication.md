# MD-08: Publish portable revision from proven learning

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** CLI/MCP publish, inspect/list immutable portable object from existing completed source run and v1 proof.

**Blocked by:** MD-01, MD-02

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC02,UC03,UC14; R02,R09; A02,A09

## Acceptance criteria
- [ ] Same inputs same portable ID; exact required profile/geometry and source provenance sealed; no target serial default.
- [ ] Reject incomplete, mismatched or tampered proof/template before publication.
- [ ] Original v1 ID/bytes/protected frames unchanged; no device action.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
