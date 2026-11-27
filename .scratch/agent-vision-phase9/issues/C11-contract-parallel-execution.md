# C11: Contract old gate and verify device overlap

**Parent:** specs/agent-vision-phase9/SPEC.md; CONTRACT.md v1 and CONTRACT_SCHEMAS.json are normative.

**What to build:** Remove only obsolete outer gate after auditing all upgraded input, metadata, registry, capture and offline paths.

**Blocked by:** C10

**Status:** REVIEW_RESOLVED_DESIGN (not dispatched)

**Traceability:** UC07,UC08,UC13,UC14,UC20; R07,R16; A06,A09,A17; F02,F05,F06,F07

## Acceptance criteria
- [ ] Real subprocess barriers prove A/B simultaneous device I/O, same-device raw vs recorded vs runtime one owner.
- [ ] Stress shared index, assets, sessions, CAS and process death; no deadlocks, lost evidence, extra input.
- [ ] Legacy regressions green; document one Store/cooperating process limit and quiescent upgrade.

## Evidence and responsibility boundary
Deliver only the stated slice, tests and concrete results. Respect predecessor contract, do not redesign other modules or mutate official Store/main/tag. One existing Orca project and worktree; serialize conflicting edits. Keep compatibility gate until C11. No fixture-as-live claims. No automatic dispatch or deployment.
