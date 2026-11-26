# MD-12: Activate portable revision and run on qualified serial

**Parent:** specs/agent-vision-phase9/SPEC.md

**What to build:** CLI/MCP portable family publish/activate and single task execute/inspect/list pin active revision, generation, exact qualification.

**Blocked by:** MD-11

**Status:** PROPOSED (ready-for-agent after review; not dispatched)

**Traceability:** UC06,UC09,UC11,UC12,UC14; R05,R06,R09; A05,A08,A09

## Acceptance criteria
- [ ] A/B run same revision with own refs and receipts; stale generation/inactive/missing or revoked qualification rejected before action.
- [ ] New revision requires new qualification; admitted task remains pinned; legacy registry unaffected.
- [ ] Duplicate/conflict and live/abandoned owner semantics preserved; failure hands off without auto-recovery.

## Evidence
Focused tests and applicable regressions; report commands, counts, artifacts, limitations. Isolated candidate Store, no official deployment or unauthorized live device actions. Keep compatibility gate until MD-07; do not claim fixture as live evidence.
