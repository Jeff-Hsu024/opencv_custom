# C10: Legacy registry and task admission

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Preserve same-device registry activation exclusion, legacy orchestrator owner through all children and atomic claims. Re-read family generation after owner acquisition.

**Blocked by:** C09

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC08,UC11,UC12,UC20; R05,R07,R14,R16; A05,A06,A08,A17; F05,F07

## Acceptance criteria
- [ ] Activation/disable/route mutation races with legacy primary/recovery/restart: waits same device, no stale generation or unexpected recovery child.
- [ ] Registry CAS and duplicate ID reconciliation preserve existing receipts and behavior; owner/device order audited.
- [ ] Unrelated device progresses after C11; no runtime re-entry for reconciliation; legacy 120s wait preserved.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
