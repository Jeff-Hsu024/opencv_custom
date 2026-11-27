# C07 Recorded Transition migration

Implemented C07 on the existing local feature branch after C06 commit
`c7a9c06`. The slice follows CONTRACT v1 K01?K04 and K08 for
UC08, UC09, UC11, UC15 and UC16.

Both transition entry points hold one device owner across the pre-capture,
reference match, click, wait and post-capture. Before input, the coordinator
commits the pending intent and increments the device epoch in one transaction.
The scoped receipt is authoritative in SQLite. Legacy requests retain their
JSON journal and original receipt shape. The compatibility gate remains in use.

Scoped transitions use the requested immutable target, optional pre-state and
optional image-wait revisions. Existing Recorder events retain matching and
wait provenance. Workflow Builder compiled and validated the scoped click
sequence offline after explicit semantic annotation. Technical observation
leaves the transition's semantic result `UNKNOWN`.

The Windows subprocess test paused inside injected platform input. The parent
observed a committed pending receipt and epoch, no post-action frame, and a
held OS device lock. After killing the writer, the same request returned the
interrupted receipt and original pending click event without another click.
The failure-evidence test checked that a timed-out image wait returns the
actual observed PNG through MCP and that a CLI duplicate returns the same
receipt. A cross-session revision was refused before input.

## Verification

Commands ran from the repository root on Windows with `PYTHONPATH=core;.`,
the `.scratch/c00-env/Scripts` Python on PATH and temporary candidate stores.

| Command or check | Result |
| --- | --- |
| `python -m pytest vision_app/test/test_transition.py vision_app/test/test_failure_evidence.py vision_app/test/test_agent_interface.py specs/agent-vision-phase9/c00/test_contract.py -q --tb=short` | Exit 0, 1,032 passed in 66.63s |
| `python -m pytest core/test vision_app/test -q` | Exit 0, 409 passed in 383.06s |
| Independent Python comparison of C00 manifest and production request validator | Exit 0, 26 frozen hashes matched and all 26 scoped transition request vectors agreed |
| `git diff --check` for C07 paths | Exit 0 |

Tests used synthetic device serials and injected platforms with real subprocess,
SQLite, filesystem, matching, Recorder and Builder paths. No Android device
input or live qualification was performed.
