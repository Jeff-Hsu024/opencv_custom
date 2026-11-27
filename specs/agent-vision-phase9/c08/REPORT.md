# C08 Legacy Runtime and Recovery migration

Implemented C08 on the existing local feature worktree after C07 commit
`0a83c3e`. The slice covers UC08, UC09, UC11 and UC14 under CONTRACT v1
K03–K05 and the K08 freeze amendment.

Legacy qualification and profile probes take the shared device owner.
A standalone run holds its request and device owners from admission through
the registry and source-device guards, captures, input and verification.
The legacy task holds its device owner across primary, selector, recovery
and restart. Its deterministic child runs share the admitted task request
owner and device owner. The compatibility gate still wraps these paths.

Before the click, the coordinator commits the step intent and device epoch.
The action uses a ref stamped from the actual protected pre-frame. The
compatibility JSON retains its original keys, and the sidecar lets inspection
project a pending step if the process stops before writing the legacy projection.
Inspection consults the request owner without waiting for the compatibility
gate. A live owner leaves the journal in `running` and recovery open returns
`DEVICE_BUSY`. Once the owner is abandoned, inspection can persist the
interruption without dispatching an effect. Terminal legacy JSON is read
directly.

The subprocess test stops inside the injected input and checks the committed
epoch, actual device lock, live inspection and unchanged journal during a
recovery-open attempt. After terminating the process it checks interruption,
the recovery handoff and original-ID duplication without replay. The timeout
test verifies the final actual PNG and its post-action epoch. The legacy
recovery-chain test verifies one recovery and one restart, consecutive epochs
and exclusion of a competing same-device owner during both clicks.

The existing in-process crash test reads the raw journal when asserting the
pending representation. Public inspection now performs dead-owner
reconciliation, which the subprocess test exercises independently.

## Verification

Commands ran from the Windows repository root with `PYTHONPATH=core;.`,
`.scratch/c00-env/Scripts` Python on PATH and a distinct temporary candidate
store for each test invocation.

| Check | Result |
| --- | --- |
| `python -m pytest vision_app/test/test_runtime.py vision_app/test/test_recovery.py vision_app/test/test_lifecycle.py vision_app/test/test_orchestrator.py specs/agent-vision-phase9/c00/test_contract.py -q --tb=short` | Exit 0, 1,039 passed in 241.26s |
| `python -m pytest core/test vision_app/test -q` | Exit 0, 410 passed in 386.05s |
| Compare the LF-normalized bytes against C00 `FREEZE.json` | Exit 0, all 26 hashes matched |
| `git diff --check` on C08 paths | Exit 0 |

The targeted run includes the frozen 61 legacy MCP definitions, CLI
names and defaults, and legacy response samples. Tests used injected
platforms with real subprocesses, locks, stores, matching and proof checks.
No Android input or live qualification was performed.
