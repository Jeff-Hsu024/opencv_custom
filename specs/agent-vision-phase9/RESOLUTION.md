# Phase 9 - Review Resolve
Status: REVIEW_RESOLVED_DESIGN. Findings closed at design level only; implementation proof and live acceptance remain open.
Reviewed commit: d53b98648a61572520b0170529b61a6e8b16b703; review bba029ebb6900f0366ce8925e6a411fb9c387c25. REVIEW.md preserved unchanged.

| Finding | Resolution | SPEC / Contract | Implementation owners | Acceptance |
|---|---|---|---|---|
| F01 HIGH | Immutable scoped asset revisions, coherent commit pointer and pinned recorder digest; legacy alias preserved | R10 / K04 | C03,C06,C07 | A11 |
| F02 HIGH | Durable device action epoch, checked under device owner; increment before possible input; explicit legacy limit | R11 / K03,K04 | C05,C06,C07,C08,P02,P05,P08 | A12 |
| F03 HIGH | Target-bound shared resolver/verifier and interpreter; source proof and legacy guard remain distinct | R12 / K05 | P01,P02,P03,P05,P08 | A13 |
| F04 HIGH | Independent qualification slot CAS, durable drift invalidation and no resurrection; family generation separate | R13 / K05 | P04,P06,P07,P08,B01 | A14 |
| F05 HIGH | Atomic parent/child reservation, distinct owner lifecycle, closed admission, no replay or live-child false interruption | R14 / K03,K06 | C04,C06,C07,C08,C10,P05,P06,P08,B01,B02 | A15 |
| F06 MEDIUM | Pinned consistent dependency snapshot, revision/seal recheck before commit, stale proof rejection | R15 / K04 | C02,C03,C09,P01,P03,P07 | A16 |
| F07 MEDIUM | Contract v1 and request schema catalog written before coding; C00 executable contract fixture gate | R16 / K01-K07 | C00,C01,C10,C11,P04,V01 | A17 |

Additional decisions: legacy registry changes share family device owner to preserve activation exclusion across a legacy recovery chain; strict discovery distinguishes failure vs valid empty, narrow Core parser fix allowed; same-host/same-store logical serial scope retained; explicit second device still not established. Batch 16 devices/4 concurrent maximum, default 2 are initial limits, not benchmark results. New CLI uses one request-file interface; new portable IDs are disjoint; no additional authentication system. Legacy unversioned coordinate/reference operations retain legacy semantics, not epoch-safe; all cooperating effects advance epoch. Source evidence changes block later admissions, not rewrite historical receipts. Already admitted executions are pinned and still enforce live state/profile. No new portable recovery or cross-host scheduling.

Ticket changes: 15 original MD tickets removed from the active issue directory, recoverable from d53b986. 21 review-proposed slices refined to 24 by separating evidence consistency from legacy registry, shared verifier from interpreter, and family revision registry from single execute. One existing Orca project and one feature worktree. C00 only initial frontier. No external issue publication, no DAG execution. Each slice references exact contract; C00 must add and freeze executable response and semantic fixtures, not redesign. Existing 308 tests are baseline target, not a new regression result.

Validation: actual NB schema and fixture files transferred read-only to isolated verification container; SHA-256 exactly matched manifest. jsonschema 4.26.0 Draft202012Validator check_schema passed 29/29. Four valid requests accepted, ten invalid requests rejected. NB official and system Python lacked jsonschema; no package installation or official environment change. Response/state-machine semantic fixtures and source implementation tests remain C00/successor responsibility. Independent EGM/fresh-agent review and real two-device E2E NOT_ATTEMPTED; V02 is separate.

Verdict: all F01-F07 have a concrete normative design resolution and named acceptance owners. Ready for C00 contract fixture freeze and subsequent reviewed implementation, not a claim of runtime qualification or release readiness.
