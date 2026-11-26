# C04 device and request ownership

C04 covers UC08, UC11 and UC18 under R07 and R14, with acceptance references
A06, A08, A15 and F05. Implementation on `feat/agent-vision-multi-device`
follows CONTRACT v1 K03/K06 and the C00 K08 amendment.

- `OwnerCoordinator` uses C02's shared OS file-lock primitive. Canonical Store,
  lock namespace and exact serial or full request ID determine the permanent
  SHA-256 lock filename. An in-process mutex and the OS lock share a contention
  deadline. Portable waits are bounded at two seconds. Legacy callers may use
  the existing 120-second limit.
- The lock order is parent, independent request, device, metadata. Nested
  device work can use the active device token on the owning thread. Attempts to
  acquire an owner from metadata, acquire a parent from a child, or acquire a
  second device fail immediately. Existing C02/C03 cleanup probes remain
  nonblocking. The compatibility workspace gate remains in place through C11.
- `RequestLedger` uses an additive `coordinator.sqlite` under the shared
  metadata transaction. The first lookup checks canonical identity before
  device or registry validation. Admission repeats that check atomically.
  Response-only `return_image` does not affect identity. A changed payload or
  admission collision returns `REQUEST_ID_CONFLICT`. An exact standalone
  invocation of a reserved child returns `ID_RESERVED`. Exact duplicates of
  running or terminal children retrieve the receipt without dispatch.
- One transaction writes a parent admission, its pins and all requested
  reservations. A child claims its task and nested run under the same owner
  while parent admission is open. Closing admission finalizes unclaimed
  reservations atomically. Order and pins come from validated service inputs.
- Inspection of an in-progress claim uses a nonblocking probe of its actual
  request owner, including the shared task owner for nested runs. Reconciliation
  runs only with that owner acquired. The effect service supplies its receipt
  policy. Terminal receipts are immutable, and the parent cannot go terminal
  while any child remains nonterminal.

## Verification

Commands ran from the repository root in Windows PowerShell with
`.scratch/c00-env` Python, `PYTHONPATH=core;.` and separate temporary
`VISION_STORE_DIR` values. C04 fixtures use synthetic serials and subprocess
barriers against temporary SQLite stores and actual OS locks. They cover
same-device contention, concurrent ownership of distinct serials, forced
process death, unchanged lock file identity, thread exclusion, valid and invalid
lock order, nested owner reuse, atomic rollback, duplicate precedence, and a
live surviving child after parent death. After child death, inspection preserves
the previously persisted unknown outcome. A Windows probe immediately after
forced termination initially observed contention. The reacquisition test
allows a bounded one-second interval for OS release.

```powershell
$env:PYTHONPATH='core;.'
$env:PATH="$PWD/.scratch/c00-env/Scripts;$env:PATH"
python -m pytest vision_app/test/test_coordinator.py vision_app/test/test_frame_transactions.py vision_app/test/test_asset_revisions.py -q
python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short
python -m pytest core/test vision_app/test -q
git diff --check
```

| Check | Exit | Result | Evidence |
| --- | --- | --- | --- |
| Coordinator, frame transactions and asset revisions | 0 | 42 passed in 43.73s | [Output](targeted-output.txt) |
| Frozen contract and legacy transport surface | 0 | 978 passed in 8.61s | [Output](contract-output.txt) |
| Full Core and Vision App regression | 0 | 396 passed in 331.82s | [Output](regression-output.txt) |
| `git diff --check` and `git diff --cached --check` | 0 | No whitespace errors | |

No device input or live qualification was performed. Runtime and adapter
integration, epoch/pending intent persistence, pinned admission policy, and
full batch reconciliation remain with the assigned successor tickets.
