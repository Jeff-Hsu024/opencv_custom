# C10 Legacy registry and task admission

C10 implements CONTRACT v1 K03 and K05 and SPEC R16 after C09
(`41bbd4e`). It covers the C10 portions of UC08, UC11, UC12 and UC20.

- Legacy registration, activation, rollback, disable, route linking and route
  status changes resolve a family device before waiting and acquire that
  device's existing owner. They re-read family identity and generation under
  the owner. The registry write and generation/history update share a short
  metadata transaction. Proof checks and image matching run outside metadata.
- Lock order is compatibility gate, then task request owner where applicable,
  then one exact device owner, then metadata. The task pins its active version
  after device acquisition and holds ownership through primary, selector,
  recovery and restart. The legacy owner and compatibility waits retain their
  120-second bounds.
- The parent and all three deterministic run IDs are claimed in one SQLite
  transaction. Historical run-journal collision checks and standalone run
  admission share metadata exclusion with that transaction. An occupied final
  child ID rolls back earlier reservations and preserves the existing claim.
- Duplicate execution checks original receipts before current registry state.
  Reconciliation of abandoned ledger-backed tasks uses the actual request
  owner and reads or finishes child journals under that owner. It can restore
  pending uncertainty and close unused child reservations without dispatch.
  Pre-ledger task journals still reconcile under the compatibility gate.

The contention tests use temporary stores, real application services, the
existing runtime image fixtures and real owners. They bypass the gate only on
the competing test path to verify the inner lock and generation ordering.
The production gate remains active for C11. Independent-device overlap remains
a C11 check. This report records software testing with fixture device effects.

## Verification

Commands run from the Windows worktree with `PYTHONPATH=core;.`, a temporary
candidate `VISION_STORE_DIR` per pytest invocation, and Python from
`.scratch/c00-env/Scripts`. The frozen hash comparison matched all 26 entries
in `c00/FREEZE.json`.

| Command | Result |
| --- | --- |
| `python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short` | Exit 0, 978 passed in 10.75s |
| `python -m pytest vision_app/test/test_lifecycle.py vision_app/test/test_orchestrator.py vision_app/test/test_runtime.py vision_app/test/test_coordinator.py -q --tb=short` | Exit 0, 58 passed in 294.04s |
| `python -m pytest core/test vision_app/test -q` | Exit 0, 419 passed in 510.48s |

The first focused run reported 1 failed and 28 passed (exit 1). It exposed a
legacy validation precedence change for duplicate registration, corrected by
checking whether the workflow is already managed before parent validation.
An intermediate full run passed 417 tests (exit 0).
A later focused run reported 11 failed and 47 passed (exit 1) and exposed an
uninitialized nested-run receipt after moving admission into metadata
exclusion. The shared initial receipt was restored and the superseded full
run was stopped. The corrected normal and interrupted task smoke tests both
passed (2 passed in 22.24s, exit 0).
