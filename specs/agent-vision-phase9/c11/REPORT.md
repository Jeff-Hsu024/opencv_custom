# C11 legacy gate contraction

Base `bfe8e9f` on the existing `feat/agent-vision-multi-device` worktree.
This slice follows CONTRACT v1 K03–K05 and the K08 freeze amendment. It
addresses UC07, UC08, UC13, UC14 and UC20 and the C11 portions of A06, A09 and
A17. V01 compatibility verification and V02 live qualification remain
independent work.

## Gate audit

| Path | Exclusion or consistency after contraction |
| --- | --- |
| Bare CLI/MCP snapshot, wait and input | Capture and input already take the exact device owner. Input advances the durable epoch before platform dispatch. Wait holds the owner through its observation loop. Offline crop, resize, ref lookup and asset access use existing frame pins and metadata transactions. |
| Legacy Recorder and recorded find/wait | A session event owns its device from admission through final event persistence. Its nested adapter effects borrow that same owner. Pause, resume and stop take the session's device owner before changing status. Event sequence and frame protection serialize under metadata. Recorded find and image wait consume the same alias snapshot and PNG retained by the event. Recorded registration retains the exact revision it publishes. |
| Legacy and scoped transitions | Request owner precedes device owner. Legacy checks, matching and wait share coherent alias snapshots, with the source-device guard at admission. Scoped operations use explicit immutable revision IDs. A legacy same-ID duplicate waits on its own request, then reads or reconciles the receipt. |
| Runtime, registry, selector and task | Runtime probe/capture, run and selector use the device owner. Family writes use the same owner and recheck generation under metadata. Task admission reserves all child IDs together and keeps the device owner through primary, selection, recovery and restart. A legacy duplicate waits on its own running request while unrelated requests proceed. Historical task reconciliation uses the same request-lock file. |
| Offline workflows and recovery | Builder validation and publication retain C09's evidence snapshots and compare at commit. Recovery prepares case evidence outside metadata and rechecks case existence inside the transaction that inserts both the session and case. Recovery qualification persistence uses metadata serialization. |
| Shared Store | Asset alias publication, index changes, retention, active pins, request claims and SQLite mutations retain their existing short metadata transactions. Device or request owner acquisition precedes metadata where both are required. |

The coordinator approved prerequisite fixes in this dispatch after an isolated
audit reproduced a legacy alias race. Before the fix, a recorded A find
retained revision A, a B writer replaced the global name, and the matcher used
B's PNG. The probe gave one match against A and zero against B, with a
successful raced receipt that still listed A's evidence. The fixed regression
forces the same interleaving through MCP for both find and image wait and
compares the retained revision and PNG digest.

## Upgrade scope

The guarantee applies to cooperating upgraded CLI/MCP processes on one host
with one ADB server and one canonical shared Store. Serial identity is exact.
Separate Stores, aliases for the same physical device and external controllers
do not share this exclusion. Stop and drain all old 0.2.0 writers before the
upgrade and take a consistent backup while quiescent. Existing historical
Store files stay in place. Rollback uses the separate consistent backup.

All tests used isolated temporary Stores. The overlap test uses real OS
subprocesses and fixture device effects. Runtime A and recorded MCP B reach
their effect barriers concurrently. Raw CLI A and recorded MCP A remain
outside their effect callbacks while Runtime A is paused, then enter one at
a time. Durable epochs count exactly three effects on A and one on B. No
Android or desktop input was sent, and this does not establish live
qualification. A second authorized compatible Android device remains required
for V02.

## Verification

Commands ran from the Windows worktree with `PYTHONPATH=core;.`, a fresh
temporary `VISION_STORE_DIR` per invocation and Python from
`.scratch/c00-env/Scripts`. All 26 LF-normalized hashes in `c00/FREEZE.json`
matched.

| Command | Result | Output |
| --- | --- | --- |
| `python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short` | Exit 0, 978 passed in 15.56s | [contract](contract-output.txt) |
| `python -m pytest vision_app/test/test_gate_contraction.py -q --tb=short` | Exit 0, 6 passed in 18.78s | [adapter and admission tests](adapter-output.txt) |
| `python -m pytest vision_app/test/test_gate_contraction.py vision_app/test/test_primitives.py -q --tb=short` | Exit 0, 11 passed in 26.83s | [contraction and scoped primitives](primitives-output.txt) |
| `python -m pytest vision_app/test/test_gate_contraction.py vision_app/test/test_frame_transactions.py vision_app/test/test_asset_revisions.py vision_app/test/test_coordinator.py vision_app/test/test_runtime.py::test_live_owner_then_process_death_inside_input vision_app/test/test_agent_interface.py::test_transition_concurrent_duplicate vision_app/test/test_orchestrator.py::test_concurrent_duplicate_serialized -q --tb=short` | Exit 0, 51 passed in 79.00s | [stress and process death](stress-output.txt) |
| `python -m pytest core/test vision_app/test -q` | Exit 0, 425 passed in 532.44s | [full regression](regression-output.txt) |

The initial full run exited 1 with 418 passes and one legacy transition
duplicate failure. Gate removal exposed same-ID admission contention before
the first receipt was published. The fix waits on that request owner, then
checks the journal again. The regression passed in the targeted run.
[Initial full output](regression-initial-output.txt)

The full regression collected the overlap test before its raw worker was
switched from MCP to CLI. The separate six-case adapter run exercised the
committed CLI variant. Production code was the same in both runs.
